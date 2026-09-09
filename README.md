# Systemy Wizyjne - Odczyt godziny z zegara analogowego

Aplikacja webowa, która na podstawie zdjęcia zegara analogowego automatycznie
wykrywa tarczę, odczytuje cyfry na tarczy, lokalizuje wskazówki i wyznacza
aktualnie wskazywaną godzinę. Projekt zaliczeniowy z przedmiotu **Systemy
Wizyjne (02 67 5361 01)**.

Aplikacja działa pod adresem: `https://systemywizyjne.pawelmiszczak.pl`

## Cel projektu

Celem projektu jest praktyczne zastosowanie metod cyfrowego przetwarzania
obrazu i widzenia komputerowego do rozwiązania konkretnego, nietrywialnego
zadania: automatycznego odczytu godziny z fotografii zegara analogowego,
zrobionej dowolnym telefonem, w warunkach niekontrolowanego oświetlenia i pod
niewielkim kątem.

Zadanie łączy kilka klasycznych zagadnień z zakresu systemów wizyjnych
(segmentacja, detekcja obiektów, OCR, transformacja Hougha, operacje
morfologiczne) w jeden kompletny, działający produkt - od modelu detekcji,
przez logikę przetwarzania obrazu, po interfejs webowy i wdrożenie na
serwerze produkcyjnym.

## Jak to działa

Przetwarzanie pojedynczego zdjęcia przebiega w kilku etapach (`clock_reader.py`):

1. **Detekcja tarczy zegara** - model YOLO (`ultralytics`, `best.pt`)
   lokalizuje tarczę zegara na zdjęciu i zwraca jej bounding box.
2. **Przycięcie i powiększenie** - wykryty obszar tarczy jest wycinany
   i skalowany (interpolacja bikubiczna), aby ułatwić dalsze etapy.
3. **OCR cyfr na tarczy** - EasyOCR odczytuje cyfry 1–12 wraz z ich
   położeniem i pewnością odczytu (próg ufności konfigurowalny).
4. **Wyznaczenie środka tarczy** - środek liczony jako mediana punktów
   przecięcia linii łączących przeciwległe cyfry (1–7, 2–8, 3–9, itd.).
5. **Maskowanie wskazówek** - segmentacja binarna oparta o próg Otsu
   w obszarze tarczy, z iteracyjnie zmienianą "siłą" progowania, dopóki nie
   uda się wyodrębnić dwóch odrębnych wskazówek.
6. **Detekcja linii wskazówek** - transformacja Hougha (`HoughLinesP`) na
   masce, z deduplikacją kandydatów (odrzucanie tego samego kierunku /
   tego samego ramienia wskazówki wykrytego wielokrotnie).
7. **Rozróżnienie wskazówki godzinowej i minutowej** - długość każdej
   wskazówki mierzona jest dodatkowo metodą "promienia ciemności"
   (`ray_darkness_length`), niezależnie od wyniku Hougha, co zwiększa
   odporność na szumy.
8. **Obliczenie godziny** - kąty obu wskazówek przeliczane są na godzinę
   i minutę, z korektą przeniesienia godziny przy wskazówce minutowej
   blisko pełnej godziny.
9. **Wizualizacja wyniku** - wygenerowany obraz z zaznaczoną tarczą, cyframi,
   maską wskazówek i odczytanym czasem jest zwracany do przeglądarki
   (base64 PNG).

Cały proces sterowany jest parametrami zebranymi w jednym miejscu
(`constants.py`), co pozwala łatwo dostrajać algorytm bez ingerencji w logikę.

## Architektura systemu

- **Frontend** (`templates/index.html`) - prosty formularz uploadu zdjęcia
  z paskiem postępu (Bootstrap 5), wskazówkami jak zrobić dobre zdjęcie
  zegara, oraz podglądem wyniku wraz z wizualizacją.
- **Backend** (`app.py`) - pojedynczy endpoint `/upload`, przyjmujący plik
  graficzny, zwracający JSON z odczytaną godziną i obrazem wynikowym.
- **Warstwa wdrożeniowa** - nginx jako reverse proxy z certyfikatem SSL,
  gunicorn jako serwer WSGI, supervisor pilnujący procesu aplikacji.

## Stack technologiczny

| Warstwa            | Technologia                                  |
|---------------------|-----------------------------------------------|
| Detekcja obiektów   | YOLO (ultralytics)                             |
| OCR                 | EasyOCR                                        |
| Przetwarzanie obrazu| OpenCV, NumPy                                  |
| Backend             | Flask + gunicorn                               |
| Frontend            | HTML/JS + Bootstrap 5                          |
| Serwer WWW          | nginx (reverse proxy, SSL)                     |
| Zarządzanie procesem| supervisor                                     |
| SSL                 | Let's Encrypt / certbot                        |

## Instalacja lokalna

Wymagany Python 3.12+.

```bash
git clone https://github.com/PMiszczak/systemywizyjne.git
cd systemywizyjne

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python app.py
```

Aplikacja domyślnie uruchamia się w trybie debug (`constants.FLASK_DEBUG`)
i jest dostępna pod `http://127.0.0.1:5000`.

> Uwaga: `requirements.txt` zawiera zależności CUDA (`torch`, `nvidia-*`)
> odpowiadające konfiguracji GPU wykorzystanej podczas developmentu. Na
> maszynie bez GPU NVIDIA warto podmienić `torch`/`torchvision` na wersję CPU
> oraz ustawić `OCR_GPU = False` w `constants.py` (już domyślnie wyłączone).

## Wdrożenie produkcyjne

Projekt zawiera dwa skrypty automatyzujące wdrożenie na czystym serwerze
Ubuntu.

### `install_systemywizyjne.sh`

Instaluje i konfiguruje całe środowisko produkcyjne:

- aktualizuje system i instaluje pakiety bazowe (git, Python, nginx,
  supervisor, narzędzia do kompilacji),
- klonuje repozytorium do `/home/systemywizyjne`,
- tworzy wirtualne środowisko i instaluje zależności z `requirements.txt`,
- ustawia uprawnienia (właściciel `www-data`, dostęp grupowy dla
  użytkownika wdrażającego),
- konfiguruje `supervisor` do uruchamiania aplikacji przez `gunicorn`,
- konfiguruje `nginx` jako reverse proxy.

```bash
sudo bash install_systemywizyjne.sh
```

### `secure_systemywizyjne.sh`

Dokłada certyfikat SSL (Let's Encrypt) dla domeny i wymusza HTTPS:

```bash
sudo bash secure_systemywizyjne.sh
```

Po uruchomieniu obu skryptów aplikacja jest dostępna pod
`https://systemywizyjne.pawelmiszczak.pl`, z automatycznym odnawianiem
certyfikatu (`certbot.timer`).

## Konfiguracja

Wszystkie parametry algorytmu (progi OCR, geometria maski, tolerancje
detekcji wskazówek, kolory wizualizacji) znajdują się w `constants.py` i są
udokumentowane nazwami zmiennych - nie wymagają zmian w kodzie logiki, by
dostroić działanie systemu do innego typu zegarów lub warunków zdjęcia.

## Odniesienie do efektów uczenia się

Projekt realizuje kierunkowe efekty uczenia się przedmiotu **Systemy
Wizyjne** w następującym zakresie:

- **Wiedza teoretyczna zastosowana praktycznie** - wykorzystanie
  poznanych na wykładzie zagadnień: modeli koloru i przestrzeni obrazu,
  operacji arytmetycznych i morfologicznych na obrazach, filtracji
  cyfrowej, segmentacji obrazu sceny (tarcza zegara jako "scena
  robotyczna"), transformacji Hougha do detekcji linii oraz analizy
  kształtu (wyznaczanie długości i kierunku wskazówek).
- **Lokalizacja i analiza obiektów na scenie** - detekcja tarczy zegara
  (odpowiednik lokalizacji obiektu na scenie), segmentacja wskazówek na
  tle tarczy, analiza ich geometrii w celu wyznaczenia wskazywanego czasu.
- **Znajomość technologii informatycznych stosowanych w układach
  automatyki** - integracja gotowych bibliotek (YOLO, EasyOCR, OpenCV) w
  spójny system produkcyjny, z uwzględnieniem wdrożenia (nginx, gunicorn,
  supervisor, SSL) - czyli pełny cykl od algorytmu do działającej usługi.
- **Praca projektowa i dokumentacja rozwiązania** - sformułowanie
  problemu, zaprojektowanie architektury rozwiązania oraz przygotowanie
  dokumentacji technicznej (niniejszy README) opisującej przyjęte
  założenia i sposób działania systemu.
