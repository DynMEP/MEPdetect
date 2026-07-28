# reCAPTCHA Integration Guide

Google reCAPTCHA v3 protects your platform from bots and spam during registration and login.

## 🔑 Setup Steps

### 1. Get reCAPTCHA Keys

1. Go to https://www.google.com/recaptcha/admin/create
2. Fill out the form:
   - **Label**: MEPdetect Production
   - **reCAPTCHA type**: Score based (v3)
   - **Domains**: 
     - `mepdetect.com`
     - `www.mepdetect.com`
     - `localhost` (for testing)
3. Click **Submit**
4. Copy your keys:
   - **Site Key**: Starts with `6L...` (public, goes in frontend)
   - **Secret Key**: Starts with `6L...` (private, goes in backend)

### 2. Configure Frontend

Update `login.html`:

```html
<!-- Replace this line: -->
<script src="https://www.google.com/recaptcha/api.js?render=6LexampleSiteKey"></script>

<!-- With your actual site key: -->
<script src="https://www.google.com/recaptcha/api.js?render=YOUR_SITE_KEY_HERE"></script>
```

Update JavaScript (3 places in login.html):

```javascript
// In handleLogin function:
const recaptchaToken = await grecaptcha.execute('YOUR_SITE_KEY_HERE', {action: 'login'});

// In handleRegister function:
const recaptchaToken = await grecaptcha.execute('YOUR_SITE_KEY_HERE', {action: 'register'});
```

### 3. Configure Backend

Update `user_api.py` or use environment variable:

**Option A: Direct in code (not recommended for production)**
```python
RECAPTCHA_SECRET_KEY = "YOUR_SECRET_KEY_HERE"
```

**Option B: Environment variable (recommended)**
```python
import os
RECAPTCHA_SECRET_KEY = os.getenv('RECAPTCHA_SECRET_KEY', '6LexampleSecretKey')
```

Then set in your environment:
```bash
# In .env file
RECAPTCHA_SECRET_KEY=YOUR_SECRET_KEY_HERE

# Or in docker-compose.yml
environment:
  - RECAPTCHA_SECRET_KEY=YOUR_SECRET_KEY_HERE
```

### 4. Configure Score Threshold

In `user_api.py`, adjust the minimum score:

```python
RECAPTCHA_MIN_SCORE = 0.5  # Default
# 0.0 = Definitely bot
# 0.5 = Moderate threshold (recommended)
# 0.7 = Strict threshold
# 1.0 = Definitely human
```

**Recommended thresholds:**
- **Registration**: 0.5 (moderate)
- **Login**: 0.3 (lenient, to avoid false positives)
- **Contact form**: 0.5 (moderate)

## 🧪 Testing

### Local Testing

1. Add `localhost` to your reCAPTCHA domain list
2. Use your real keys (test keys won't work properly)
3. Test registration and login

### Check Score

View reCAPTCHA scores in logs:
```bash
docker-compose logs -f user-api | grep reCAPTCHA
```

Output:
```
✅ reCAPTCHA v3 verified: score=0.9
❌ reCAPTCHA v3 failed: score=0.1, success=True
```

### Test Commands

```bash
# Register with valid token (from browser console)
grecaptcha.execute('YOUR_SITE_KEY', {action: 'register'}).then(token => {
    console.log('Token:', token);
    // Use this token in your API call
});
```

## 🔒 Security Best Practices

### 1. Keep Secret Key Private

❌ **Never commit to Git:**
```python
# Bad
RECAPTCHA_SECRET_KEY = "6LdRcP..."  # Don't do this!
```

✅ **Use environment variables:**
```python
# Good
RECAPTCHA_SECRET_KEY = os.getenv('RECAPTCHA_SECRET_KEY')
```

### 2. Validate on Server-Side

❌ **Don't trust frontend only:**
```javascript
// Bad - frontend check only
if (recaptchaScore > 0.5) {
    // Submit form
}
```

✅ **Always verify on backend:**
```python
# Good - server-side verification
if not await verify_recaptcha(token):
    raise HTTPException(400, "Failed verification")
```

### 3. Handle Errors Gracefully

```python
async def verify_recaptcha(token: str) -> bool:
    try:
        # Verification logic
        return True
    except httpx.TimeoutException:
        # Log error but allow request (with rate limiting)
        logger.warning("reCAPTCHA timeout - allowing request")
        return True  # Fail-open for availability
    except Exception as e:
        logger.error(f"reCAPTCHA error: {e}")
        return False  # Fail-closed for security
```

## 📊 Monitoring

### 1. View Analytics

Go to https://www.google.com/recaptcha/admin and select your site:
- View request volume
- See score distribution
- Identify bot attacks

### 2. Adjust Thresholds

Based on analytics:
- High false positives? → Lower threshold (0.3-0.4)
- Bot attacks? → Raise threshold (0.6-0.7)
- Monitor weekly and adjust

### 3. Alert on Anomalies

```python
# Add monitoring
if score < 0.3:
    logger.warning(f"Low reCAPTCHA score: {score} from {ip_address}")
    # Send alert to admin
```

## 🚨 Troubleshooting

### "Invalid site key"
- Check site key matches domain
- Verify domain is added in reCAPTCHA console
- Clear browser cache

### "Timeout connecting to Google"
- Check server can reach www.google.com
- Verify no firewall blocking outbound HTTPS
- Consider increasing timeout: `timeout=10.0`

### "Score always 0.1"
- Likely bot or headless browser
- Check user agent
- Verify action name matches

### "Failed verification" errors
- Verify secret key is correct
- Check logs for specific error codes
- Ensure token is used only once

## 🔄 Fallback Strategy

For critical failures:

```python
RECAPTCHA_BYPASS_FOR_ERRORS = True  # Only for high availability

async def verify_recaptcha(token: str) -> bool:
    try:
        # Normal verification
        return await _verify_with_google(token)
    except Exception as e:
        logger.error(f"reCAPTCHA service error: {e}")
        
        if RECAPTCHA_BYPASS_FOR_ERRORS:
            # Log and allow (add to review queue)
            logger.warning("Bypassing reCAPTCHA due to service error")
            return True
        else:
            # Strict mode - deny on error
            return False
```

## 🌐 Alternative: reCAPTCHA v2 (Checkbox)

For users with accessibility needs:

```html
<!-- Add visible checkbox -->
<div class="g-recaptcha" data-sitekey="YOUR_SITE_KEY"></div>
<script src="https://www.google.com/recaptcha/api.js"></script>
```

Backend handles both v2 and v3 automatically.

## 📈 Expected Results

After implementation:
- ✅ 90%+ reduction in spam registrations
- ✅ Block automated account creation
- ✅ Prevent credential stuffing attacks
- ✅ Maintain good user experience (invisible)

## 📞 Support

- Google reCAPTCHA Docs: https://developers.google.com/recaptcha/docs/v3
- Report issues: reCAPTCHA console → Support
- MEPdetect help: support@mepdetect.com
