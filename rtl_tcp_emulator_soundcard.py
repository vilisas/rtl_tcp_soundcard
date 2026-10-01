#!/usr/bin/env python3
#
# Kodas sugeneruotas Gemini
#
#

import sys
import socket
import threading
import struct
import numpy as np
import sounddevice as sd
import scipy.signal as signal

# --- KONFIGŪRACIJA ---
HOST = '0.0.0.0'
PORT = 1234
AUDIO_RATE = 48000     
CHANNELS = 2           
TARGET_RATE = 250000   

gcd = np.gcd(TARGET_RATE, AUDIO_RATE)
UP_FACTOR = TARGET_RATE // gcd
DOWN_FACTOR = AUDIO_RATE // gcd


# Tikriname, ar terminale buvo nurodytas argumentas (pvz.: python skriptas.py 25)
if len(sys.argv) > 1:
    try:
        DEFAULT_GAIN_DB = float(sys.argv[1])
    except ValueError:
        print("Klaida: Gain turi būti skaičius. Naudojamas standartinis 20.0 dB")
        DEFAULT_GAIN_DB = 20.0
else:
    DEFAULT_GAIN_DB = 20.0  # Standartinė reikšmė, jei argumentas neįvestas

# Konvertuojame dB į linijinį daugiklį
gain_multiplier_default = 10 ** (DEFAULT_GAIN_DB / 20.0)
gain_multiplier = gain_multiplier_default
print(f"SDR emuliatorius paleistas su: {DEFAULT_GAIN_DB} dB ({gain_multiplier:.2f}x stiprinimas)")

# Globalus kintamasis garso stiprinimui
#gain_multiplier = 1.0

def handle_client(client_socket):
    global gain_multiplier
    print("SDR++ prisijungė!")
    
    # 12 baitų magiška antraštė: 'RTL0' + Tuner R820T (5) + 29 gain žingsniai
    magic_header = b'RTL0' + struct.pack('>II', 5, 29)
    try:
        client_socket.sendall(magic_header)
    except Exception as e:
        print(f"Nepavyko nusiųsti antraštės: {e}")
        client_socket.close()
        return

    def audio_callback(indata, frames, time, status):
        global gain_multiplier
        if status:
            print(status)
        try:
            # Taikome programinį stiprinimą
            i_signal = indata[:, 0] * gain_multiplier
            q_signal = indata[:, 1] * gain_multiplier
            
            # Resampling iki 250 kHz
            i_resampled = signal.resample_poly(i_signal, UP_FACTOR, DOWN_FACTOR)
            q_resampled = signal.resample_poly(q_signal, UP_FACTOR, DOWN_FACTOR)
            
            new_frames = len(i_resampled)
            
            # Konvertuojame į uint8 (0-255)
            i_uint8 = ((i_resampled + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
            q_uint8 = ((q_resampled + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
            
            iq_interleaved = np.empty((new_frames * 2,), dtype=np.uint8)
            iq_interleaved[0::2] = i_uint8
            iq_interleaved[1::2] = q_uint8
            
            client_socket.sendall(iq_interleaved.tobytes())
        except Exception:
            raise sd.CallbackStop

    # Paleidžiame audio srautą
    stream = sd.InputStream(samplerate=AUDIO_RATE, channels=CHANNELS, blocksize=2048, callback=audio_callback)
    stream.start()
    
    print(f"Srautas paleistas. Laukiama SDR++ komandų...")

    # Klausomės valdymo komandų iš SDR++
    while True:
        try:
            cmd_data = client_socket.recv(5)
            if not cmd_data or len(cmd_data) < 5:
                break
            
            # PATAISYTA: cmd_data[0] iškart grąžina sveikąjį skaičių (int)
            cmd_type = cmd_data[0]
            cmd_param = struct.unpack('>I', cmd_data[1:5])[0]
            
            # Komanda 0x04: SET_GAIN
            if cmd_type == 4:
                gain_db = cmd_param / 10.0
                # db konversija į linijinį daugiklį
                gain_multiplier = 10 ** (gain_db / 20.0)
                print(f"[SDR++] Slankiklis pajudintas: {gain_db} dB -> Daugiklis: {gain_multiplier:.2f}x")
                
            # Komanda 0x03: SET_GAIN_MODE (0 = Auto, 1 = Manual)
            elif cmd_type == 3:
                if cmd_param == 0:
#                    gain_multiplier = gain_multiplier_default
                    gain_multiplier = 1.0
                    print(f"[SDR++] SDR++ pasirinko Auto Gain (Atstatoma į {gain_multiplier:.2f}x)")
                else:
                    print("[SDR++] SDR++ įjungė rankinį Gain režimą")
            
            # Komanda 0x08: SET_AGC_MODE (Kitas būdas, kuriuo programos bando valdyti AGC)
            elif cmd_type == 8:
                print(f"[SDR++] RTL AGC režimas pakeistas į: {cmd_param}")

        except Exception as e:
            print(f"Klaida apdorojant komandą: {e}")
            break

    print("SDR++ atsijungė. Stabdomas srautas.")
    stream.stop()
    stream.close()
    client_socket.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f"rtl_tcp serveris paruoštas porte {PORT}...")
    
    try:
        while True:
            client_sock, addr = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_sock,))
            client_thread.start()
    except KeyboardInterrupt:
        print("\nServeris stabdomas.")
    finally:
        server.close()

if __name__ == '__main__':
    main()
