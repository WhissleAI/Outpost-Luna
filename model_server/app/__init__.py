import os

# ONNX Runtime's official builds ship Microsoft's 1DS telemetry, on by default (native code, Azure endpoints). Off before
# any module here loads onnxruntime or libarc: the app promises no network after setup (desktop/runtime/launch.py too).
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
