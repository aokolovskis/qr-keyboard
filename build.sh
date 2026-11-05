#!/bin/sh
# Builds QRKeyboard.app (ad-hoc signed) in ./build
set -e
cd "$(dirname "$0")"
APP=build/QRKeyboard.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp Info.plist "$APP/Contents/Info.plist"
swiftc -O Sources/main.swift -o "$APP/Contents/MacOS/QRKeyboard" \
  -framework AppKit -framework AVFoundation -framework ApplicationServices -framework Vision
codesign --force --sign - "$APP"
echo "Built $APP"
echo "Run:  open $APP        (or $APP/Contents/MacOS/QRKeyboard --no-enter --cooldown 5)"
