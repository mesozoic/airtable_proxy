# airtable_proxy

This is intended to be a lightweight proxy for the Airtable API which trades data freshness for higher speeds. It uses [webhooks](https://airtable.com/developers/web/api/model/webhooks-payload) to tail all changes to a base's records and update a local cache. As a result, it is limited to certain operations.

## Dependencies

This library relies on:

- [pyairtable](https://pyairtable.rtfd.org)
- [fastapi](https://fastapi.tiangolo.com)
- [sqlite3](https://docs.python.org/3/library/sqlite3.html)

## Getting started

Create a configuration file that looks like this:

```yaml
hostname: airtable-proxy.yourcompany.com
bases:
    appCRvRn3LxhzqYUZ:
        api_key: patCRvRn3LxhzqYUZ.s3Lxh...
```
