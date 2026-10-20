---
title: Publishing the Site to S3
parent: Continuous Benchmarking
grand_parent: User Guide
nav_order: 80
---

# Publishing the Site to S3

`reportr` builds a directory of static files with no server-side component, so publishing is a file copy. S3 is the natural destination when the results already live there.

## Build and publish are separate

```bash
reportr build --serve                        # look at it first
reportr build --publish                      # build, then upload to site.publish_to
reportr publish --to s3://my-bucket/public   # upload an existing build
reportr publish --to s3://my-bucket/public --dry-run
```

Building is pure: reports in, a directory out. Publishing is the step others can see. Keeping them apart means `--serve` shows exactly what would go live, and a failed upload never leaves a half-rendered site in place.

{: .note }
Publishing never deletes. The obvious tidy-up — remove anything in the bucket that is not in this build — would be wrong here, because the benchmark results live under the same prefix as the site. A prune that understood only the site would delete the history on its first run.

## Bucket layout

```
s3://my-bucket/
└── public/                      # world-readable
    ├── index.html               # the site
    ├── app.js  style.css  vendor/
    ├── data/*.json              # chart data
    ├── reports/<run-id>.json    # the report behind each plotted point
    └── v1/runs/...              # the stored results themselves
```

Everything under `public/` is readable; everything outside it is not. Keeping the results under the same public prefix is deliberate — a reader who clicks through to a data point gets the real report, not a summary.

## What the bucket policy needs

Anonymous read on the public prefix, and listing scoped to the same prefix so the contents can be browsed:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadUnderPublicPrefix",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::my-bucket/public/*",
      "Condition": {"Bool": {"aws:SecureTransport": "true"}}
    },
    {
      "Sid": "PublicListUnderPublicPrefixOnly",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-bucket",
      "Condition": {
        "StringLike": {"s3:prefix": "public/*"},
        "Bool": {"aws:SecureTransport": "true"}
      }
    }
  ]
}
```

Note that `s3:ListBucket` is a *bucket-level* action and takes the bare bucket ARN, while `s3:GetObject` takes the `bucket/*` form. Getting this wrong is the most common reason a policy appears to do nothing.

The bucket's public access block must also permit a public policy: `BlockPublicPolicy` and `RestrictPublicBuckets` set to false. Leave both ACL flags true — the policy is the only thing that should be able to expose an object.

Omitting `s3:ListBucket` is a reasonable choice if you would rather readers could not enumerate the prefix; the site itself works either way, since every asset it needs is linked.

## The published URL

```
https://my-bucket.s3.eu-north-1.amazonaws.com/public/index.html
```

Two things about that URL are not accidents.

{: .important }
**It names `index.html` explicitly**, because the bucket has no S3 *website* configuration — and cannot have a useful one. Website endpoints are HTTP-only, so the `aws:SecureTransport` condition above would reject every request to them. The plain REST endpoint serves no default document in exchange, which is why the path is explicit. Every asset reference in the site is relative, so it works correctly under any prefix.

**It names the region.** The cross-region endpoint answers with a 307 redirect; browsers follow it, but `curl` and `fetch` without redirect handling do not. `reportr` emits the regional form.

## Verifying

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  https://my-bucket.s3.eu-north-1.amazonaws.com/public/index.html
# 200 text/html; charset=utf-8
```

Check the content type, not just the status. S3 labels objects `binary/octet-stream` unless told otherwise, and a browser handed that for `index.html` downloads the file instead of rendering it. `reportr` sets the type explicitly per file extension rather than relying on the host's MIME database.

Confirm too that nothing outside the public prefix is reachable:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  https://my-bucket.s3.eu-north-1.amazonaws.com/private-prefix/anything
# 403
```

## Other destinations

`publish_to` also accepts a filesystem path, which covers copying the site to a web server's document root, into a container image, or onto a volume another process serves. The site is static and makes no third-party requests, so anything that can serve files can host it.
