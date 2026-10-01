#!/bin/sh
# A self-signed certificate for the dev server, so a phone on the same network can reach it.
#
# This is not about encryption. Browsers refuse camera and microphone access outside a secure
# context, and "secure" means HTTPS or localhost — so http://192.168.x.x:5173 is blocked
# outright, however much you trust your own LAN. This cert is what makes the dev server a
# secure context for a phone.
#
# Every LAN address of this machine goes in as a subjectAltName, because a browser checks the
# name it was asked for against the certificate and a bare CN has not been honoured for years.
#
# Development only. The certificate is self-signed, so a browser will warn and you accept the
# warning. Never use it for anything a patient's data passes through.
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)/frontend/certs"
DAYS=365
mkdir -p "$DIR"

ADDRESSES=$(hostname -I 2>/dev/null || true)
ALT="DNS:localhost,IP:127.0.0.1,IP:::1"
for address in $ADDRESSES; do
  case "$address" in
    *:*) ALT="$ALT,IP:$address" ;;
    *)   ALT="$ALT,IP:$address" ;;
  esac
done

echo "issuing a development certificate for: $ALT"
openssl req -x509 -nodes -newkey rsa:2048 -days "$DAYS" \
  -keyout "$DIR/dev-key.pem" -out "$DIR/dev-cert.pem" \
  -subj "/CN=painsense-dev" \
  -addext "subjectAltName=$ALT" \
  -addext "basicConstraints=CA:FALSE" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null

chmod 600 "$DIR/dev-key.pem"
echo "written to frontend/certs/"
echo
echo "Start the dev server and it will pick the certificate up:"
echo "  cd frontend && npm run dev"
echo
echo "Then open it on your phone, on the same network, at one of:"
for address in $ADDRESSES; do
  case "$address" in
    *:*) : ;;
    *) echo "  https://$address:5173" ;;
  esac
done
echo
echo "Your browser will warn that the certificate is not trusted. Accept the warning:"
echo "  Chrome / Android:  Advanced -> Proceed"
echo "  Safari / iOS:      Show Details -> visit this website -> Visit Website"
echo "Camera and microphone will not be offered until you do."
