"""웹 푸시 알림용 VAPID 키를 한 번 생성한다.

사용법:
    pip install pywebpush
    python scripts/generate_vapid_keys.py

출력되는 값을 아래처럼 등록한다:
  - Private Key -> GitHub 저장소 Settings > Secrets > Actions 에 VAPID_PRIVATE_KEY 로 등록
  - Public Key  -> pwa/app.js 상단의 VAPID_PUBLIC_KEY 값으로 붙여넣기
"""
from py_vapid import Vapid02
import base64


def main():
    vapid = Vapid02()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    private_b64 = base64.urlsafe_b64encode(private_raw).rstrip(b"=").decode()

    public_numbers = vapid.public_key.public_numbers()
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    public_raw = b"\x04" + x + y
    public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode()

    print("=== VAPID Private Key (GitHub Secret: VAPID_PRIVATE_KEY) ===")
    print(private_b64)
    print()
    print("=== VAPID Public Key (pwa/app.js: VAPID_PUBLIC_KEY) ===")
    print(public_b64)


if __name__ == "__main__":
    main()
