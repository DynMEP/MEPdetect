#!/usr/bin/env python3
"""
Test reCAPTCHA Integration
Verify that reCAPTCHA is properly configured
"""

import asyncio
import httpx
import sys

# Configuration
RECAPTCHA_SECRET_KEY = "YOUR_SECRET_KEY_HERE"  # Update this
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
TEST_TOKEN = "YOUR_TEST_TOKEN_HERE"  # Get from browser console


async def test_recaptcha_verification():
    """Test reCAPTCHA verification"""
    
    print("🔐 Testing reCAPTCHA Integration\n")
    print("=" * 50)
    
    # Check secret key
    if RECAPTCHA_SECRET_KEY == "YOUR_SECRET_KEY_HERE":
        print("❌ ERROR: Update RECAPTCHA_SECRET_KEY in this script")
        print("   Get your secret key from: https://www.google.com/recaptcha/admin")
        return False
    
    print(f"✓ Secret Key: {RECAPTCHA_SECRET_KEY[:10]}...")
    
    # Get test token
    if TEST_TOKEN == "YOUR_TEST_TOKEN_HERE":
        print("\n📝 To get a test token:")
        print("1. Open your login page in browser")
        print("2. Open browser console (F12)")
        print("3. Run: grecaptcha.execute('YOUR_SITE_KEY', {action: 'test'})")
        print("4. Copy the token and update TEST_TOKEN in this script")
        return False
    
    print(f"✓ Test Token: {TEST_TOKEN[:20]}...")
    
    # Verify with Google
    print("\n🔄 Verifying with Google...")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                RECAPTCHA_VERIFY_URL,
                data={
                    'secret': RECAPTCHA_SECRET_KEY,
                    'response': TEST_TOKEN
                },
                timeout=10.0
            )
            
            result = response.json()
            
            print(f"\n📊 Response from Google:")
            print(f"   Success: {result.get('success')}")
            print(f"   Score: {result.get('score', 'N/A')}")
            print(f"   Action: {result.get('action', 'N/A')}")
            print(f"   Challenge TS: {result.get('challenge_ts', 'N/A')}")
            print(f"   Hostname: {result.get('hostname', 'N/A')}")
            
            if 'error-codes' in result:
                print(f"   Errors: {result.get('error-codes')}")
            
            # Evaluate result
            if result.get('success'):
                score = result.get('score', 0)
                if score >= 0.5:
                    print(f"\n✅ PASS: reCAPTCHA verification successful! (score: {score})")
                    return True
                else:
                    print(f"\n⚠️  WARNING: Score too low ({score} < 0.5)")
                    print("   This might be flagged as a bot")
                    return False
            else:
                print("\n❌ FAIL: Verification failed")
                return False
                
    except httpx.TimeoutException:
        print("\n❌ ERROR: Timeout connecting to Google")
        print("   Check internet connection and firewall")
        return False
    
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False


async def test_api_endpoint():
    """Test registration endpoint with reCAPTCHA"""
    
    print("\n" + "=" * 50)
    print("🌐 Testing API Endpoint\n")
    
    api_url = "http://localhost:8093/auth/register"
    
    # This will fail (expected) but tests the endpoint
    test_data = {
        "email": "test@example.com",
        "password": "testpass123",
        "full_name": "Test User",
        "recaptcha_token": "invalid_token"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url,
                json=test_data,
                timeout=10.0
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
            
            if response.status_code == 400:
                detail = response.json().get('detail', '')
                if 'reCAPTCHA' in detail:
                    print("\n✅ API correctly rejects invalid reCAPTCHA tokens")
                    return True
            
            print("\n⚠️  Unexpected response from API")
            return False
            
    except httpx.ConnectError:
        print("❌ ERROR: Cannot connect to API")
        print("   Make sure API is running on port 8093")
        return False
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False


def print_setup_instructions():
    """Print setup instructions"""
    
    print("\n" + "=" * 50)
    print("📋 Setup Instructions\n")
    
    print("1. Get reCAPTCHA Keys:")
    print("   → https://www.google.com/recaptcha/admin/create")
    print()
    print("2. Update Secret Key:")
    print("   → In this script: RECAPTCHA_SECRET_KEY")
    print("   → In .env file: RECAPTCHA_SECRET_KEY")
    print()
    print("3. Update Site Key:")
    print("   → In login.html: grecaptcha.execute('YOUR_SITE_KEY', ...)")
    print()
    print("4. Test in browser:")
    print("   → Open login page")
    print("   → Check browser console for errors")
    print("   → Try registering an account")
    print()
    print("See RECAPTCHA_SETUP.md for detailed guide")
    print("=" * 50)


async def main():
    """Run all tests"""
    
    print("\n")
    print("╔════════════════════════════════════════════════╗")
    print("║     MEPdetect reCAPTCHA Integration Test      ║")
    print("╚════════════════════════════════════════════════╝")
    print()
    
    # Test 1: Verification
    test1_pass = await test_recaptcha_verification()
    
    # Test 2: API endpoint
    test2_pass = await test_api_endpoint()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary\n")
    print(f"   reCAPTCHA Verification: {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"   API Integration:        {'✅ PASS' if test2_pass else '❌ FAIL'}")
    print("=" * 50)
    
    if test1_pass and test2_pass:
        print("\n🎉 All tests passed! reCAPTCHA is configured correctly.")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Review the output above.")
        print_setup_instructions()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
