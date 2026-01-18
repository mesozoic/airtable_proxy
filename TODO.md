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
    - [ ] If a webhook exists:
        - [ ] read the webhook cursor number from local storage
        - [ ] trigger the "read webhook payloads" job
        - [ ] re-run the job every 1s after it completes

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

- [ ] "Read webhook payloads" job
    - [ ] Retrieve payloads and store for async processing
    - [ ] Process webhook payloads in order, in the background
    - [ ] Need to support webhook payloads that:
        - [ ] create a new table
        - [ ] create a new field
        - [ ] rename a field
        - [ ] destroy a field
        - [ ] create a record
        - [ ] change a record's field values
        - [ ] destroy a record
    - [ ] Need to ensure every operation above is idempotent wrt local storage
    - [ ] Only update the local cursor value once a payload is processed

- [ ] Support [list records](https://airtable.com/developers/web/api/list-records)
    - [ ] implement `maxRecords`
    - [ ] implement `sort`
    - [ ] implement `fields`
    - [ ] implement `returnFieldsByFieldId`
    - [ ] ignore `recordMetadata`; we don't need to support it now
    - [ ] ignore `pageSize`; we will never return multiple pages
    - [ ] ignore `offset`; we will never return multiple pages
    - [ ] proxy to Airtable if the `view=` parameter is non-empty
    - [ ] proxy to Airtable if the `filterByFormula=` parameter is non-empty
    - [ ] proxy to Airtable if `cellFormat=string`
    - [ ] proxy to Airtable if table is missing from local storage

- [ ] Support [get record](https://airtable.com/developers/web/api/get-record)
    - [ ] implement `returnFieldsByFieldId`
    - [ ] proxy to Airtable if `cellFormat=string`
    - [ ] proxy to Airtable if record is missing from local storage

## 0.2

- [ ] Make the polling interval configurable

## 1.0

- [ ] Allow disabling polling interval in the configuration
    - This means we _only_ refresh payloads when we receive a notification
- [ ] Switch to use Celery or RQ for background tasks
