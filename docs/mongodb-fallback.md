# MongoDB Fallback

SPARX uses Firestore as the primary database. The fallback layer mirrors repository writes into MongoDB and reads from MongoDB immediately when a Firestore repository operation fails, times out, is quota-limited, or is not configured.

This is a detachable local resilience layer. It is intentionally isolated under `backend/app/fallbacks/`.

## Runtime Files

- `backend/app/fallbacks/policy.py` decides when a Firestore error should fail over.
- `backend/app/fallbacks/mongo_store.py` owns Mongo reads/writes and the local JSON emergency buffer.
- `backend/app/database/fallback_utils.py` is a compatibility shim for existing repository imports.
- `backend/app/database/mongo_fallback.py` is a compatibility shim for existing repository imports.
- `backend/start_mongodb.ps1` starts either a local `mongod.exe` or Docker MongoDB.

## Environment

```env
FIRESTORE_OPERATION_TIMEOUT_SECONDS=3
MONGODB_FALLBACK_ENABLED=true
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=sparx
```

`FIRESTORE_OPERATION_TIMEOUT_SECONDS` keeps failover quick. Firestore remains primary, but the backend will not wait through long SDK retry delays before Mongo is used.

## Local Setup

Run:

```powershell
.\backend\start_mongodb.ps1
```

The script checks for MongoDB in this order:

1. `mongod` on PATH.
2. Portable MongoDB under `tools\mongodb`.
3. MongoDB installed under `C:\Program Files\MongoDB`.
4. Docker Compose using `docker-compose.mongo.yml`.

Local Mongo data is stored in `backend\.mongodb-data\db` and logs go to `backend\logs\mongod.log`. Both paths are ignored by git.

## Read and Write Behavior

- Create/update/delete calls write to Firestore first, then mirror to Mongo.
- If Firestore fails, the same write continues into Mongo.
- List/get calls read Firestore first and mirror fresh records into Mongo.
- If Firestore fails, list/get calls read Mongo.
- If Mongo is temporarily unavailable on a local machine, `backend\.local_fallback` keeps a small JSON emergency buffer so newly written records are not lost during development.

## Detaching For Production

Soft detach, recommended first:

1. Set `MONGODB_FALLBACK_ENABLED=false`.
2. Remove `MONGODB_URI` and `MONGODB_DATABASE` from production secrets.
3. Keep the fallback files in the repo until the production release is verified.

Hard detach, after production no longer needs the fallback:

1. Remove `backend/app/fallbacks/`.
2. Remove `backend/app/database/fallback_utils.py` and `backend/app/database/mongo_fallback.py`, or replace repository imports with direct Firestore-only handling.
3. Remove Mongo fallback calls from repositories:
   - `mongo_fallback_service.upsert(...)`
   - `mongo_fallback_service.get(...)`
   - `mongo_fallback_service.list(...)`
   - `mongo_fallback_service.delete(...)`
   - `mongo_fallback_service.append_array_item(...)`
4. Remove `MONGODB_*` and `FIRESTORE_OPERATION_TIMEOUT_SECONDS` from env examples if no longer needed.
5. Remove this document and `backend/start_mongodb.ps1` if local Mongo development is no longer supported.

## Verification

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_fallback_policy.py
@'
from pymongo import MongoClient
client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500)
print(client.admin.command("ping"))
print(client["sparx"].list_collection_names())
'@ | .\backend\.venv\Scripts\python.exe -
```
