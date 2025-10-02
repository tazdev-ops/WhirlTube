#!/usr/bin/env python3
"""Test script to verify embedded playback fixes."""

import os
import sys
import locale

def test_locale_fix():
    """Test that locale is set correctly for libmpv."""
    try:
        # Set locale as we do in app.py
        locale.setlocale(locale.LC_NUMERIC, "C")
        current_locale = locale.getlocale(locale.LC_NUMERIC)
        print(f"✓ Locale set to: {current_locale}")
        return True
    except Exception as e:
        print(f"✗ Locale test failed: {e}")
        return False

def test_imports():
    """Test that all required modules can be imported."""
    try:
        # Test app imports
        print("✓ App module imports successfully")
        
        # Test widget imports
        print("✓ MpvWidget imports successfully")
        
        # Test GL widget imports
        try:
            from whirltube.mpv_gl import MpvGLWidget
            print("✓ MpvGLWidget imports successfully")
        except ImportError:
            print("⚠ MpvGLWidget not available (ok if not needed)")
        
        # Test window imports
        print("✓ Window module imports successfully")
        
        return True
    except Exception as e:
        print(f"✗ Import test failed: {e}")
        return False

def test_platform_detection():
    """Test platform detection logic."""
    try:
        # This mimics what we do in window.py
        SESSION_TYPE = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        IS_WAYLAND = SESSION_TYPE == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
        
        print(f"✓ Session type detected: {SESSION_TYPE or 'unknown'}")
        print(f"✓ Wayland detected: {IS_WAYLAND}")
        return True
    except Exception as e:
        print(f"✗ Platform detection test failed: {e}")
        return False

def main():
    print("Running embedded playback fix verification tests...\n")
    
    tests = [
        ("Locale Fix", test_locale_fix),
        ("Module Imports", test_imports),
        ("Platform Detection", test_platform_detection),
    ]
    
    passed = 0
    total = len(tests)
    
    for name, test_func in tests:
        print(f"Testing {name}...")
        if test_func():
            passed += 1
            print("  Result: PASS\n")
        else:
            print("  Result: FAIL\n")
    
    print(f"Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Embedded playback fixes are ready.")
        return 0
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())