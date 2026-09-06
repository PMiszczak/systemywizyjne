sed -i '/^django-environ==/d' requirements.txt
pip install -r requirements.txt --no-cache-dir