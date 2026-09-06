import base64

import cv2
import numpy as np
import easyocr
from flask import Flask, render_template, request, jsonify
from ultralytics import YOLO

import constants as c
from clock_reader import read_clock

app = Flask(__name__)
model = YOLO(c.MODEL_PATH)
reader = easyocr.Reader(c.OCR_LANGUAGES, gpu=c.OCR_GPU, verbose=False)


def image_to_b64(img):
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf).decode("ascii") if ok else None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("photo")
    if not file or file.filename == "":
        return jsonify({"error": "Nie wybrano zdjecia."}), 400

    data = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"error": "Nie udalo sie wczytac zdjecia."}), 400

    time, vis = read_clock(img, model, reader)
    if time is None:
        return jsonify({"error": "Nie znaleziono zegara albo wskazowek na zdjeciu."}), 200

    hour, minute = time
    return jsonify({
        "result_time": f"{hour:02d}:{int(round(minute)) % 60:02d}",
        "result_image": image_to_b64(vis),
    })


if __name__ == "__main__":
    app.run(debug=c.FLASK_DEBUG)
