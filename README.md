# librespot-python-ppc

Trying to figure out if I can find some way to stream music from Spotify on a sunflower iMac G4 (PowerPC)...who knows if this will work? current idea is backporting [librespot-python](https://github.com/kokarare1212/librespot-python) to python 2.7. This may be a terrible idea...

The program is currently stopping on below line of code within the Session.connect method which essentially means no response is being read from Spotify's servers after sending the client hello proto message.
```bash
ap_response_message_length = self.connection.read_int()
```

## Installation

You first need to install [Python 2.7.15](https://www.python.org/downloads/release/python-2715/)

Clone this repo into your workspace/local computer:

```bash
cd librespot-python-ppc
```

Create a python virtual environment via virtualenv pip package:
```bash
virtualenv myenv
```
Activate your virtual environment:
```bash
source myenv/bin/activate
```
Install dependencies via requirements.txt file in root directory:

```bash
 pip install -r requirements.txt
```
Start the application:
```bash
python main.py
```
