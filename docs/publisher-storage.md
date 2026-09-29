# Setting up picture delivery for Publisher conversion

Google Slides can only place a picture it fetches from a web link, and it
accepts no Drive file for this. So when a Publisher file is converted, each
picture goes through a private Cloud Storage bucket (DECISIONS.md,
2026-09-28):

1. the app stores a copy under a random name;
2. it asks Google to sign a link that works for 15 minutes;
3. Slides fetches the picture once, through that link;
4. the app deletes the copy as soon as that page is built.

A lifecycle rule removes anything left behind within a day. Nothing is ever
shared publicly, and the signed-in person's own Google access never touches
the bucket.

**These are billable Google Cloud resources, so the repository documents them
and does not create them.** At a school's scale the cost is effectively nil:
a few megabytes stored for a few seconds each.

Until `PUBLISHER_BUCKET` is set, `.pub` files can still be checked but not
converted, and the page says so.

## What you need

- The Google Cloud project that holds the app's OAuth client.
- Owner or equivalent rights on it, to create a bucket and grant roles.
- The `gcloud` CLI, or the Cloud Console (each step names both).

Below, replace:

| Placeholder | With |
|---|---|
| `PROJECT` | your project ID, for example `workspace-migration-toolkit` |
| `BUCKET` | a globally unique name, for example `wmt-publisher-pictures-PROJECT` |
| `SIGNER` | the service account that signs links (step 3) |
| `YOU` | your own Google account, for running the app on your machine |

## 1. Turn on the APIs

```bash
gcloud services enable storage.googleapis.com iamcredentials.googleapis.com slides.googleapis.com --project PROJECT
```

In the Console, go to **APIs & Services → Library** and enable Cloud Storage,
IAM Service Account Credentials API and Google Slides API.

## 2. Create the bucket: private, in the UK, emptied daily

```bash
gcloud storage buckets create gs://BUCKET --project PROJECT --location europe-west2 --uniform-bucket-level-access --public-access-prevention
```

Save this as `lifecycle.json`:

```json
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]}
```

```bash
gcloud storage buckets update gs://BUCKET --lifecycle-file lifecycle.json
```

In the Console: **Cloud Storage → Buckets → Create**.
- Location: *Region, europe-west2 (London)*.
- Access control: *Uniform*.
- Tick *Enforce public access prevention*.

Then on the bucket's **Lifecycle** tab, add a rule to delete objects older
than 1 day.

## 3. The service account that signs the links

On Cloud Run, use the service's own runtime service account. To run the app
on your own machine, you can create one just for this:

```bash
gcloud iam service-accounts create wmt-pictures --project PROJECT --display-name "Workspace toolkit picture links"
```

Either way, that account is `SIGNER`: for example
`wmt-pictures@PROJECT.iam.gserviceaccount.com`. Give it access to the bucket
only (to store, read and delete objects), not the whole project:

```bash
gcloud storage buckets add-iam-policy-binding gs://BUCKET --member serviceAccount:SIGNER --role roles/storage.objectUser
```

## 4. Allow links to be signed as that account

Google signs the link on the app's behalf (IAM `signBlob`), so no key file
is ever downloaded. Whoever the app runs as needs the **Service Account
Token Creator** role *on `SIGNER`*.

On Cloud Run, the runtime account signs as itself:

```bash
gcloud iam service-accounts add-iam-policy-binding SIGNER --member serviceAccount:SIGNER --role roles/iam.serviceAccountTokenCreator
```

On your own machine, the app uses your `gcloud` login. That login also
stores the pictures, so it needs both roles:

```bash
gcloud iam service-accounts add-iam-policy-binding SIGNER --member user:YOU --role roles/iam.serviceAccountTokenCreator
```

```bash
gcloud storage buckets add-iam-policy-binding gs://BUCKET --member user:YOU --role roles/storage.objectUser
```

```bash
gcloud auth application-default login
```

In the Console: go to **IAM & Admin → Service Accounts**, open `SIGNER`, and
under **Principals with access** grant *Service Account Token Creator*.

**Do not create or download a key** for the service account. The app refuses
to read one; a key file is a long-lived secret on disk.

## 5. Tell the app

| Variable | Value |
|---|---|
| `PUBLISHER_BUCKET` | `BUCKET` (the name only, no `gs://`) |
| `PUBLISHER_SIGNER` | `SIGNER`. Optional on Cloud Run, where it defaults to the service's own account |

Restart the app. **Convert** then appears for `.pub` files.

## Verified so far

Set up exactly as above in the project on 2026-09-29, with no key created:

- a link signed as `SIGNER` for 15 minutes fetched a test picture (HTTP 200);
- the same object's plain URL was refused (HTTP 403), so the bucket is private.

`gcloud storage sign-url` needed `--region europe-west2`, because it looks up
the bucket's region and `SIGNER` rightly has no bucket-level read. The app
does not: it signs with the `auto` region, as Google's published signing
examples do.

## Not yet verified against Google

Until the first live run (Publisher step 4):

- that Slides itself fetches pictures through these links;
- that `presentations.create` keeps an A5 page size;
- that a gcloud login with Token Creator can sign as `SIGNER`.
