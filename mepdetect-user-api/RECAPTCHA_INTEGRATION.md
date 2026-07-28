# reCAPTCHA Integration Summary

## ✅ What Was Added

### 1. Frontend Protection (login.html)

**Added reCAPTCHA v3 Script:**
```html
<script src="https://www.google.com/recaptcha/api.js?render=YOUR_SITE_KEY"></script>
```

**Updated Login Function:**
```javascript
const recaptchaToken = await grecaptcha.execute('YOUR_SITE_KEY', {action: 'login'});
```

**Updated Register Function:**
```javascript
const recaptchaToken = await grecaptcha.execute('YOUR_SITE_KEY', {action: 'register'});
```

### 2. Backend Verification (user_api.py)

**Added Dependencies:**
- `httpx` for async HTTP requests
- `os` for environment variables

**New Configuration:**
```python
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
RECAPTCHA_MIN_SCORE = float(os.getenv("RECAPTCHA_MIN_SCORE", "0.5"))
RECAPTCHA_ENABLED = os.getenv("RECAPTCHA_ENABLED", "true").lower() == "true"
```

**New Function:**
```python
async def verify_recaptcha(token: str, action: str = None) -> bool:
    """Verify reCAPTCHA token with Google API"""
    # Supports both v2 and v3
    # Score-based validation for v3
    # Can be disabled for testing
```

**Updated Endpoints:**
- `/auth/register` - Now requires and validates reCAPTCHA token
- `/auth/login` - Now requires and validates reCAPTCHA token

**Updated Pydantic Models:**
```python
class UserRegister(BaseModel):
    recaptcha_token: str  # Added

class UserLogin(BaseModel):
    recaptcha_token: str  # Added
```

### 3. Configuration Files

**docker-compose-full.yml:**
```yaml
environment:
  - RECAPTCHA_SECRET_KEY=${RECAPTCHA_SECRET_KEY}
  - RECAPTCHA_MIN_SCORE=${RECAPTCHA_MIN_SCORE:-0.5}
  - RECAPTCHA_ENABLED=${RECAPTCHA_ENABLED:-true}
```

**.env.example:**
```bash
RECAPTCHA_SECRET_KEY=YOUR_RECAPTCHA_SECRET_KEY
RECAPTCHA_SITE_KEY=YOUR_RECAPTCHA_SITE_KEY
RECAPTCHA_ENABLED=true
```

**deploy.sh:**
- Added reCAPTCHA key to generated .env
- Updated setup instructions

### 4. Documentation

**New Files:**
- `RECAPTCHA_SETUP.md` - Complete setup guide
- `test_recaptcha.py` - Testing script
- `.env.example` - Environment template

**Updated Files:**
- `USER_MANAGEMENT_README.md` - Added security section
- `QUICKSTART.md` - Added reCAPTCHA config steps

## 🚀 Quick Setup

### Step 1: Get reCAPTCHA Keys
```bash
# Go to: https://www.google.com/recaptcha/admin/create
# Create a v3 site key
# Copy Site Key and Secret Key
```

### Step 2: Update Frontend
```bash
# Edit login.html (3 locations)
# Replace: 6LexampleSiteKey
# With: YOUR_ACTUAL_SITE_KEY
```

### Step 3: Update Backend
```bash
# Create .env from template
cp .env.example .env

# Edit .env
RECAPTCHA_SECRET_KEY=your_secret_key_here
```

### Step 4: Test
```bash
# Update test_recaptcha.py with your keys
python3 test_recaptcha.py

# Or test via browser
# 1. Open login page
# 2. Try registering
# 3. Check server logs for reCAPTCHA scores
```

## 🔧 Configuration Options

### Score Threshold
```bash
# Strict (fewer bots, more false positives)
RECAPTCHA_MIN_SCORE=0.7

# Moderate (recommended)
RECAPTCHA_MIN_SCORE=0.5

# Lenient (fewer false positives, more bots)
RECAPTCHA_MIN_SCORE=0.3
```

### Disable for Testing
```bash
# In .env
RECAPTCHA_ENABLED=false

# reCAPTCHA will be bypassed
# Useful for automated testing
```

### Different Thresholds per Action
```python
# In user_api.py, customize verification:
if action == 'login':
    min_score = 0.3  # More lenient for login
elif action == 'register':
    min_score = 0.5  # Stricter for registration
```

## 📊 How It Works

### Flow Diagram
```
User fills form
    ↓
JavaScript calls grecaptcha.execute()
    ↓
Google generates token (includes score)
    ↓
Token sent to backend with form data
    ↓
Backend verifies token with Google API
    ↓
Google returns: {success, score, action}
    ↓
Backend checks: score >= threshold?
    ↓
Allow/Deny based on score
```

### reCAPTCHA v3 Scores
- **0.0 - 0.3**: Likely bot
- **0.3 - 0.6**: Suspicious
- **0.6 - 0.9**: Probably human
- **0.9 - 1.0**: Very likely human

### Error Handling
```python
# Timeout → Fail-closed (deny)
# API Error → Log and deny
# Disabled → Allow (for testing)
# Invalid token → Deny
# Low score → Deny
```

## 🧪 Testing Checklist

- [ ] Get reCAPTCHA keys from Google
- [ ] Update site key in login.html (3 places)
- [ ] Update secret key in .env
- [ ] Start user API
- [ ] Open login page in browser
- [ ] Check browser console (no errors)
- [ ] Try registering a user
- [ ] Check server logs for verification
- [ ] Confirm registration succeeds
- [ ] Try with VPN/proxy (should get lower score)
- [ ] Run test_recaptcha.py script

## 🔒 Security Benefits

### Before reCAPTCHA
- ❌ Vulnerable to automated registration
- ❌ Credential stuffing attacks
- ❌ Spam account creation
- ❌ Brute force login attempts

### After reCAPTCHA
- ✅ Blocks automated bots (90%+ reduction)
- ✅ Invisible to legitimate users
- ✅ Adaptive challenge (v3 scores)
- ✅ No CAPTCHA puzzles (better UX)
- ✅ Protects login and registration

## 📈 Expected Results

### Metrics to Monitor
1. **reCAPTCHA Scores Distribution**
   - Most legitimate users: 0.7-1.0
   - Suspicious traffic: 0.3-0.6
   - Bots: 0.0-0.3

2. **Registration Success Rate**
   - Before: Accept all (including bots)
   - After: ~95% legitimate, ~5% rejected (bots)

3. **False Positive Rate**
   - Target: <1% legitimate users blocked
   - Monitor and adjust threshold

### Viewing Analytics
```bash
# In Google reCAPTCHA Admin Console:
# - Request volume
# - Score distribution
# - Bot detection rate
# - Challenge success rate
```

## 🐛 Common Issues

### Issue: "Invalid site key"
**Solution:** 
- Verify domain is added in reCAPTCHA console
- Check for typos in site key
- Ensure using correct environment (test vs prod)

### Issue: Always score 0.1
**Solution:**
- Likely bot or automation
- Check if using headless browser
- Verify action name matches

### Issue: High false positives
**Solution:**
- Lower threshold: `RECAPTCHA_MIN_SCORE=0.3`
- Check if VPN users are affected
- Review score distribution

### Issue: Can't test locally
**Solution:**
- Add `localhost` to allowed domains
- Use actual site keys (not test keys)
- Check browser console for errors

## 📞 Support

- **Google Docs**: https://developers.google.com/recaptcha/docs/v3
- **Admin Console**: https://www.google.com/recaptcha/admin
- **MEPdetect Docs**: See RECAPTCHA_SETUP.md
- **Test Script**: Run test_recaptcha.py

## ✨ Next Steps

1. **Monitor Performance**
   - Track scores for 1 week
   - Adjust threshold if needed
   - Review false positive rate

2. **Optimize Thresholds**
   - Different per action (login vs register)
   - Geographic variations
   - Time-of-day patterns

3. **Add to More Endpoints**
   - Contact form
   - Password reset
   - API key generation
   - Critical operations

4. **Implement Logging**
   - Log all verifications
   - Track patterns
   - Alert on anomalies
