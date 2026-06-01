# MongoDB Fallback

SPARX uses Firestore as the primary database. The MongoDB integration mirrors important records into MongoDB and can read from MongoDB when Firestore is unavailable, not configured, or hitting quota/rate-limit errors.

## Local Setup

1. Install Docker Desktop.
2. Start MongoDB:

```powershell
.\backend\start_mongodb.ps1
```

3. Enable fallback in `backend/.env`:

```env
MONGODB_FALLBACK_ENABLED=true
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=sparx
```

4. Start the backend normally.

MongoDB collections are created automatically when records are written. The backend also creates useful indexes for calls, callbacks, campaigns, campaign contacts, and scheduled calls.

## Collections

- `calls`
- `callbacks`
- `campaigns`
- `campaign_contacts`
- `scheduled_calls`

## Behavior

- Firestore remains the source of truth when it is healthy.
- Writes are mirrored to MongoDB when fallback is enabled.
- Reads fall back to MongoDB when Firestore is unavailable, not configured, or quota-limited.
- If MongoDB is disabled or unavailable, the app continues using Firestore normally.
