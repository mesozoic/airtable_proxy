# Todo List

## MVP

- [ ] On server startup:
    - [ ] read a configuration file with connection info and list of bases
    - [ ] test the connection to Airtable; exit if unavailable
    - [ ] for each base, check local storage for a webhook ID
        - [ ] if none is recorded, look for an existing webhook
        - [ ] use our callback URL to identify *our* webhook
    - [ ] If no webhook exists:
        - [ ] create a webhook with callback URL and save its ID
        - [ ] retrieve all records from all tables and save them locally
    - [ ] If a webhook exists:
        - [ ] load all locally saved records into memory
        - [ ] retrieve all webhook payloads and save for local processing

- [ ] Local storage for records (start with sqlite3)
    - [ ] store records with unique key of `(appId, baseId, tableId, recordId)`
    - [ ] store field values by field ID, not field name
    - [ ] store table metadata, including field names

- [ ] Poll for webhook payloads every 1s and save them for local processing
- [ ] Process webhook payloads in order
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
