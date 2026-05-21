# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.

import bz2
import json
import logging
import os
from abc import ABC, abstractmethod

from tqdm import tqdm
from osbenchmark import exceptions
from osbenchmark.utils import console
from osbenchmark.workload_generator.config import CustomWorkload

DOCS_COMPRESSOR = bz2.BZ2Compressor
COMP_EXT = ".bz2"


_SOLR_INTERNAL_FIELDS = {"_version_"}


def _cursor_scan(client, collection, batch_size=1000):
    """Iterate all documents in a Solr collection using CursorMark deep-pagination.

    Requires the collection's sort field to include a uniqueKey field (``id asc``).
    Each yielded document is a plain dict with Solr internal fields (``_version_``) removed.
    """
    cursor = "*"
    session = client._get_session()  # pylint: disable=protected-access
    url = f"{client.base_url}/solr/{collection}/select"
    while True:
        resp = session.get(
            url,
            params={"q": "*:*", "rows": batch_size, "sort": "id asc",
                    "cursorMark": cursor, "wt": "json"},
            timeout=client.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data["response"]["docs"]
        if not docs:
            break
        for doc in docs:
            yield {k: v for k, v in doc.items() if k not in _SOLR_INTERNAL_FIELDS}
        next_cursor = data.get("nextCursorMark", cursor)
        if next_cursor == cursor:
            break
        cursor = next_cursor

class IndexExtractor:
    def __init__(self, custom_workload, client):
        self.custom_workload: CustomWorkload = custom_workload
        self.client = client
        self.logger = logging.getLogger(__name__)

    def extract_indices(self, workload_path):
        extracted_indices, failed_indices = [], []
        try:
            for index in self.custom_workload.indices:
                extracted_indices += self.extract(workload_path, index.name)
        except exceptions.BenchmarkNotFoundError:
            raise exceptions.SystemSetupError(f"Collection [{index.name}] does not exist.")
        except Exception:  # pylint: disable=broad-except
            self.logger.error("Failed at extracting collection [%s]", index)
            failed_indices += index

        return extracted_indices, failed_indices

    def extract(self, outdir, collection):
        """
        Extracts and writes the Solr schema of a collection to
        "<collection>.json" in the workload directory.

        :param outdir: destination directory
        :param collection: name of the Solr collection
        :return: list of dicts with metadata for the extracted collection
        """
        results = []
        schema_obj = self.extract_collection_schema(collection)
        for name, schema in schema_obj.items():
            filename = f"{name}.json"
            outpath = os.path.join(outdir, filename)
            with open(outpath, "w") as outfile:
                json.dump(schema, outfile, indent=4, sort_keys=True)
                outfile.write("\n")
            results.append({"name": name, "path": outpath, "filename": filename})
        return results

    def extract_collection_schema(self, collection):
        """
        Retrieve the Solr schema for *collection* and return it as a dict
        keyed by collection name.

        :param collection: name of the Solr collection
        :return: ``{collection_name: schema_dict}``
        """
        results = {}
        valid, reason = self.is_valid_collection(collection)
        if valid:
            schema = self.client.get_schema(collection)
            results[collection] = schema
        else:
            self.logger.info("Skipping collection [%s] (reason: %s).", collection, reason)
        return results

    def is_valid_collection(self, name):
        if len(name) == 0:
            return False, "Collection name is empty"
        if name.startswith("."):
            return False, f"Collection [{name}] is hidden"
        return True, None


class CorpusExtractor(ABC):

    @abstractmethod
    def extract_documents(self, index, documents_limit=None, sample_frequency=None):
        pass


class SequentialCorpusExtractor(CorpusExtractor):
    DEFAULT_TEST_MODE_DOC_COUNT = 1000
    DEFAULT_TEST_MODE_SUFFIX = "-1k"

    def __init__(self, custom_workload, client):
        self.custom_workload: CustomWorkload = custom_workload
        self.client = client
        self.logger = logging.getLogger(__name__)

    def template_vars(self,index_name, docs_path, doc_count):
        comp_outpath = docs_path + COMP_EXT
        return {
            "index_name": index_name,
            "filename": os.path.basename(comp_outpath),
            "path": comp_outpath,
            "doc_count": doc_count,
            "uncompressed_bytes": os.path.getsize(docs_path),
            "compressed_bytes": os.path.getsize(comp_outpath)
        }

    def _get_doc_outpath(self, outdir, name, suffix=""):
        return os.path.join(outdir, f"{name}-documents{suffix}.json")


    def extract_documents(self, index, documents_limit=None, sample_frequency=None):
        """
        Scan a Solr collection with CursorMark pagination, dumping documents to
        ``outdir/documents.json``.

        :param index: Name of the Solr collection to dump
        :param documents_limit: Maximum number of documents to extract
        :param sample_frequency: frequency with which to sample documents

        :return: dict of properties describing the corpus for templates
        """

        total_documents = self.client.count_documents(index)

        documents_to_extract = total_documents if not documents_limit else min(total_documents, documents_limit)

        # Provide warnings for edge-cases when document limit put in place
        if documents_limit:
            # Only time when documents-1k.json will be less than 1K documents is
            # when the documents_limit is < 1k documents or source index has less than 1k documents
            if documents_limit < self.DEFAULT_TEST_MODE_DOC_COUNT:
                test_mode_warning_msg = "Due to --number-of-docs set by user, " + \
                    f"test-mode docs will be less than the default {self.DEFAULT_TEST_MODE_DOC_COUNT} documents."
                console.warn(test_mode_warning_msg)

            # Notify users when they specified more documents than available in index
            if documents_limit > total_documents:
                documents_to_extract_warning_msg = f"User requested extraction of {documents_limit} documents " + \
                    f"but there are only {total_documents} documents in {index}. " + \
                    f"Will only extract {total_documents} documents from {index}."
                console.warn(documents_to_extract_warning_msg)

        if sample_frequency and sample_frequency > 1:
            # documents_limit does not work with sample frequency which is why it's not here
            return self.sample_frequency_extraction(total_documents, sample_frequency, index)
        else:
            return self.standard_extraction(total_documents, documents_to_extract, index)


    def sample_frequency_extraction(self, total_documents, sample_frequency, index):
        if total_documents > 0:
            self.logger.info("[%d] total docs in index [%s]. Extracting [%s] docs with sample frequency [%s]", total_documents, index, total_documents, sample_frequency)

            self.dump_documents(
                self.client,
                index,
                self._get_doc_outpath(self.custom_workload.workload_path, index, self.DEFAULT_TEST_MODE_SUFFIX),
                min(total_documents, self.DEFAULT_TEST_MODE_DOC_COUNT),
                " for test mode")

            docs_path = self._get_doc_outpath(self.custom_workload.workload_path, index)
            self.dump_documents_with_sample_frequency(total_documents, sample_frequency, docs_path, index)

            amount_of_docs_to_extract = (total_documents // sample_frequency)
            return self.template_vars(index, docs_path, amount_of_docs_to_extract)
        else:
            self.logger.info("Skipping corpus extraction for index [%s] as it contains no documents.", index)

        return None

    def standard_extraction(self, total_documents, documents_to_extract, index):
        if documents_to_extract > 0:
            self.logger.info("[%d] total docs in index [%s]. Extracting [%s] docs.", total_documents, index, documents_to_extract)
            docs_path = self._get_doc_outpath(self.custom_workload.workload_path, index)
            # Create test mode corpora
            self.dump_documents(
                self.client,
                index,
                self._get_doc_outpath(self.custom_workload.workload_path, index, self.DEFAULT_TEST_MODE_SUFFIX),
                min(documents_to_extract, self.DEFAULT_TEST_MODE_DOC_COUNT),
                " for test mode")
            # Create full corpora
            self.dump_documents(self.client, index, docs_path, documents_to_extract)

            return self.template_vars(index, docs_path, documents_to_extract)
        else:
            self.logger.info("Skipping corpus extraction fo index [%s] as it contains no documents.", index)
            return None

    def dump_documents_with_sample_frequency(self, number_of_docs_in_index, sample_frequency, docs_path, index):
        number_of_docs_to_fetch = number_of_docs_in_index // sample_frequency
        number_of_docs_left = number_of_docs_to_fetch

        progress_message = f"Extracting documents for index [{index}] with sample_frequency of {sample_frequency}"

        self.logger.info("Number of docs in index: [%s], number of docs to fetch: [%s]", number_of_docs_in_index, number_of_docs_to_fetch)

        self.logger.info("sample_frequency: [%s]", sample_frequency)

        compressor = DOCS_COMPRESSOR()
        comp_outpath = docs_path + COMP_EXT

        with open(docs_path, "wb") as outfile:
            with open(comp_outpath, "wb") as comp_outfile:
                self.logger.info("Dumping corpus for index [%s] to [%s].", index, docs_path)
                progress_bar = tqdm(range(number_of_docs_to_fetch), desc=progress_message, ascii=' >=', bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}')

                for n, doc in enumerate(_cursor_scan(self.client, collection=index), start=1):
                    if (n % sample_frequency) != 0:
                        continue

                    if number_of_docs_left == 0:
                        break

                    number_of_docs_left -= 1

                    data = (json.dumps(doc, separators=(",", ":")) + "\n").encode("utf-8")

                    outfile.write(data)
                    comp_outfile.write(compressor.compress(data))
                    progress_bar.update(1)

                comp_outfile.write(compressor.flush())

    def dump_documents(self, client, index, docs_path, number_of_docs, progress_message_suffix=""):
        logger = logging.getLogger(__name__)
        freq = max(1, number_of_docs // 1000)

        progress = console.progress()
        compressor = DOCS_COMPRESSOR()
        comp_outpath = docs_path + COMP_EXT
        with open(docs_path, "wb") as outfile:
            with open(comp_outpath, "wb") as comp_outfile:
                logger.info("Dumping corpus for index [%s] to [%s].", index, docs_path)
                for i, doc in enumerate(_cursor_scan(client, collection=index)):
                    if i >= number_of_docs:
                        break
                    data = (json.dumps(doc, separators=(",", ":")) + "\n").encode("utf-8")

                    outfile.write(data)
                    comp_outfile.write(compressor.compress(data))

                    self.render_progress(progress, progress_message_suffix, index, i + 1, number_of_docs, freq)

                comp_outfile.write(compressor.flush())
        progress.finish()


    def render_progress(self, progress, progress_message_suffix, index, cur, total, freq):
        if cur % freq == 0 or total - cur < freq:
            msg = f"Extracting documents for index [{index}]{progress_message_suffix}..."
            percent = (cur * 100) / total
            progress.print(msg, f"{cur}/{total} docs [{percent:.1f}% done]")
