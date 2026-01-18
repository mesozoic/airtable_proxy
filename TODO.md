# Todo List

## MVP

- [x] Launch an ASGI server
- [x] On server startup:
    - [x] read a configuration file with connection info and list of bases
    - [x] test the connection to Airtable; exit if unavailable
    - [ ] for each base, check local storage for a webhook ID
        - [ ] if none is recorded, look for an existing webhook
        - [ ] use our callback URL to identify *our* webhook
    - [ ] If a webhook exists:
        - [ ] load records from local storage into memory
        - [ ] read the webhook cursor number from local storage
        - [ ] enqueue a "fetch webhook payloads" background job
    - [ ] If no webhook exists:
        - [ ] create a webhook with identifying callback URL
        - [ ] save webhook ID and cursor number into local storage
        - [ ] enqueue "refresh tables" background job

- [ ] Authentication
    - [ ] Use the api_key in the configuration to retrieve records
    - [ ] Hash the bearer token and check against local storage
        - [ ] If hash present and allowed, allow access
        - [ ] If hash not present, check base access by retrieving one record directly from Airtable using the bearer token
            - [ ] If successful, store hash and allow access
            - [ ] If not successful, return 403

- [ ] Local storage for records (start with sqlite3)
    - [ ] store records with unique key of `(appId, baseId, tableId, recordId)`
    - [ ] store field values by field ID, not field name
    - [ ] store table metadata, including field names

- [ ] "Refresh tables" background job
    - [ ] Pause "refresh webhook payloads" background job for this base
    - [ ] Update the locally stored cursor value for the webhook
    - [ ] Request all records from each table
    - [ ] Enqueue "refresh webhook payloads" background job

- [ ] "Refresh webhook payloads" background job
    - [ ] Poll for webhook payloads every 1s
        - [ ] Do this by triggering itself after it's done running
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

## 2.0

- [ ] Configurable backends for
    - [ ] Redis
    - [ ] Memcache
    - [ ] Postgres
