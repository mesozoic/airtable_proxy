# Todo List

## MVP

- [x] Launch an ASGI server
- [x] On poller startup:
    - [x] read a configuration file with connection info and list of bases
    - [x] test the connection to Airtable; exit if unavailable
    - [x] for each base, check local storage for a webhook ID
        - [x] if none is recorded, look for an existing webhook
        - [x] use our callback URL to identify *our* webhook
    - [x] If no webhook exists:
        - [x] create a webhook with identifying callback URL
        - [x] save webhook ID and cursor number into local storage
        - [x] fetch all tables and records
    - [x] If a webhook exists:
        - [x] read the webhook cursor number from local storage
        - [x] trigger the "read webhook payloads" job
        - [x] re-run the job every 1s after it completes

- [ ] Authentication
    - [ ] Use the api_key in the configuration to retrieve records
    - [ ] Hash the bearer token and check against local storage
        - [ ] If hash present and allowed, allow access
        - [ ] If hash not present, check base access by retrieving one record directly from Airtable using the bearer token
            - [ ] If successful, store hash and allow access
            - [ ] If not successful, return 403

- [x] Local storage for records (start with sqlite3)
    - [x] store records with unique key of `(baseId, tableId, recordId)`
    - [x] store field values by field ID, not field name
    - [x] store table metadata, including field names

- [x] "Read webhook payloads" job
    - [x] Retrieve payloads and store for async processing
    - [x] Process webhook payloads in order, in the background
    - [x] Need to support webhook payloads that:
        - [x] create a new table
        - [x] rename a table
        - [x] destroy a table
        - [x] create a new field
        - [x] rename a field
        - [x] destroy a field
        - [x] create a record
        - [x] change a record's field values
        - [x] destroy a record
    - [x] Need to ensure every operation above is idempotent wrt local storage
    - [x] Only update the local cursor value once a payload is processed

- [x] Proxy anything starting with `/v0/` that isn't handled by a route
    - [x] Pass along the existing Bearer token when proxying to Airtable
    - [x] If our application handles a route, we might _still_ need to proxy, so make it easy for us to say "never mind, just proxy the request and return whatever Airtable gives back".

- [x] Support [list records](https://airtable.com/developers/web/api/list-records)
    - [x] return all records from local storage, with fields keyed by name
    - [x] implement `maxRecords`
    - [x] implement `fields` by ID
    - [x] implement `fields` by name
    - [x] implement `returnFieldsByFieldId`
    - [x] ignore `sort` for MVP
    - [x] ignore `recordMetadata` for MVP
    - [x] ignore `pageSize` for MVP
    - [x] ignore `offset` for MVP
    - [x] proxy to Airtable if the `view=` parameter is non-empty
    - [x] proxy to Airtable if the `filterByFormula=` parameter is non-empty
    - [x] proxy to Airtable if `cellFormat=string`
    - [x] proxy to Airtable if table is missing from local storage

- [ ] Support [get record](https://airtable.com/developers/web/api/get-record)
    - [ ] implement `returnFieldsByFieldId`
    - [ ] proxy to Airtable if `cellFormat=string`
    - [ ] proxy to Airtable if record is missing from local storage

## 0.2

- [ ] Make the polling interval configurable
- [ ] Handle edge case when webhook has been deleted
- [ ] Support [get base schema](https://airtable.com/developers/web/api/get-base-schema)
    - [ ] Refresh schema when webhook is created
    - [ ] Refresh schema if we've run out of webhook payloads
    - [ ] Need to support webhook payloads that:
        - [ ] create a new table
        - [ ] rename a table
        - [ ] destroy a table
        - [ ] create a new field
        - [ ] change a field
        - [ ] destroy a field

## 1.0

- [ ] Allow disabling polling interval in the configuration
    - This means we _only_ refresh payloads when we receive a notification
- [ ] Switch to use Celery or RQ for background tasks
