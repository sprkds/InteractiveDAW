"""Interactive camera preview using OpenCV.

Run with:
  python -m laptop_node.tests.cam_preview --index 1 [--api DSHOW|MSMF|ANY]
Press 'q' or ESC to exit.
"""

from __future__ import annotations

import argparse

import cv2

API_MAP = {
    "DSHOW": getattr(cv2, "CAP_DSHOW", 0),
    "MSMF": getattr(cv2, "CAP_MSMF", 0),
    "ANY": getattr(cv2, "CAP_ANY", 0),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=0, help="Camera index")
    parser.add_argument("--api", choices=list(API_MAP.keys()), default="ANY", help="Backend API")
    parser.add_argument("--flip", action="store_true", help="Flip horizontally for preview")
    args = parser.parse_args()

    api_flag = API_MAP[args.api]
    print(f"Opening camera index={args.index} api={args.api} ({api_flag})")
    cap = cv2.VideoCapture(args.index, api_flag)
    if not cap.isOpened():
        print("Failed to open camera")
        return
    cv2.namedWindow("cam_preview", cv2.WINDOW_NORMAL)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("read() failed")
            break
        if args.flip:
            frame = cv2.flip(frame, 1)
        cv2.imshow("cam_preview", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

