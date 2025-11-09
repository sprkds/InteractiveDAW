"""Camera backend probe for Windows/Linux.

Run with:
  python -m laptop_node.tests.cam_probe --index 1
"""

from __future__ import annotations

import argparse

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=0, help="Camera index to probe")
    args = parser.parse_args()

    candidates = [
        (getattr(cv2, "CAP_DSHOW", 0), "DSHOW"),
        (getattr(cv2, "CAP_MSMF", 0), "MSMF"),
        (getattr(cv2, "CAP_ANY", 0), "ANY"),
    ]

    print(f"Probing camera index={args.index}")
    for api, name in candidates:
        try:
            cap = cv2.VideoCapture(args.index, api)
            ok = cap.isOpened()
            print(f"{name}: {ok}")
            if ok:
                # try grab one frame for sanity
                ret, _ = cap.read()
                print(f"{name}: read_frame={ret}")
            cap.release()
        except Exception as exc:  # pragma: no cover
            print(f"{name}: error {exc}")


if __name__ == "__main__":
    main()

