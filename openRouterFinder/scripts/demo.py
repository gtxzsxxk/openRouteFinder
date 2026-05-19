"""CLI demo for route finding."""

import json
import sys

sys.path.insert(0, str(__file__).rsplit("/openRouterFinder", 1)[0])

from openRouterFinder.core.data_loader import search_route


def main():
    print("OpenRouteFinder CLI Demo")
    print("========================")
    while True:
        orig = input("Enter origin ICAO (or 'q' to quit): ").strip().upper()
        if orig == "Q":
            break
        dest = input("Enter destination ICAO: ").strip().upper()
        result = search_route(orig, dest)
        if result is None:
            print("No route found.")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
