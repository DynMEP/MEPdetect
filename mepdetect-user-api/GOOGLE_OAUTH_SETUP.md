# Google OAuth setup (Sign in with Google)

MEPdetect uses [Google Identity Services](https://developers.google.com/identity/gsi/web) (ID token). One flow handles both **sign in** and **sign up**.

## 1. Google Cloud Console

1. Open [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
2. Create **OAuth 2.0 Client ID** → Application type: **Web application**.
3. **Authorized JavaScript origins** (add every environment you use):
   - `https://mepdetect.com`
   - `http://localhost:8090` (local landing page)
4. Copy the **Client ID** into `.env` as `GOOGLE_CLIENT_ID`.
5. `GOOGLE_CLIENT_SECRET` is optional for this flow (ID token only); keep it empty unless you add server redirect flows later.

## 2. Environment

In `mepdetect-user-api/.env` or root `.env`:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```

Restart the user-api container after changing env vars.

## 3. API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/google/config` | Returns `{ client_id, enabled }` for the login page |
| POST | `/auth/google` | Body: `{ "credential": "<Google ID token>" }` → JWT access + refresh tokens |

## 4. Behavior

- **New user**: account created with `auth_provider=google`, email marked verified (no verification email).
- **Existing email (password account)**: Google is linked on first Google sign-in; user can still use password login.
- **Google-only account**: password login returns a message to use Google sign-in.

## 5. Frontend

`mepdetect-frontend/login.html` loads the Google button from `/auth/google/config` and posts the credential to `/auth/google`.

Rebuild/redeploy the **landing-page** image after updating `login.html`.
