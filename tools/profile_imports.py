import time

start_all = time.time()
start = time.time()
import os
import sys

print(f"Built-ins: {time.time() - start:.3f}s")

start = time.time()
import webview

print(f"webview: {time.time() - start:.3f}s")

start = time.time()
import jot.app_webview

print(f"jot.app_webview: {time.time() - start:.3f}s")

print(f"Total time to start: {time.time() - start_all:.3f}s")
