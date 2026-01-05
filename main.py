import bluetooth
from dataclasses import dataclass
import inspect
import threading
import queue
import time
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console


@dataclass
class Response:
    sequence: bytes | None
    command: bytes | None
    id: bytes | None
    payload_size: int | None
    payload: bytearray | None
    error: str | None = None

@dataclass
class Payload:
    battery_l: bytes | None = None
    battery_r: bytes | None = None
    battery_case: bytes | None = None
    name: str | None = None
    error: str | None = None

class ComHandler:
    paired = False
    c_case: int
    device_name: str

    PAIR_COMMAND = bytes.fromhex("27")

    PAIR_0 = bytes.fromhex("ff00")
    PAIR_1 = bytes.fromhex("0100020003000400050006000700080009000a000b000c000d000e000f00100011001200130014001500160017001800fe002000")
    PAIR_2 = bytes.fromhex("0c00")

    GAME_MODE_COMMAND = bytes.fromhex("25")
    SPATIAL_AUDIO_COMMAND = bytes.fromhex("36")
    EARBUD_FUNCTIONALITY_COMMAND = bytes.fromhex("22")
    SOUND_PROFILE_COMMAND = bytes.fromhex("20")

    TOGGLE_ON = bytes.fromhex("01")
    TOGGLE_OFF = bytes.fromhex("00")

    BATTERY_INDEX = 2
    BATTERY_OFFSET = 5

    NAME_LENGTH_OFFSET = 12
    NAME_OFFSET = 12

    LEFT_BUD = 1
    RIGHT_BUD = 2

    # single tap, double tap, triple tap
    TAP_AMNT = [0, 2, 4]

    NONE = bytes.fromhex('0100')
    PLAY_PAUSE = bytes.fromhex('0107')
    LAST_TRACK = bytes.fromhex('0103')
    NEXT_TRACK = bytes.fromhex('0104')
    VOL_UP = bytes.fromhex('0105')
    VOL_DOWN = bytes.fromhex('0106')
    # 78:15:2D:5F:CE:43
    # 0101 unknown
    # 0102 unknown
    # either my packet capture wasn't as thorough as I'd like or those values don't correspond to my specific device

    PRESETS = [
        bytes.fromhex('01fdfe0401020103000000'),
        bytes.fromhex('020a0604fffefd01000000'),
        bytes.fromhex('030302fd03ff0302050000'),
        bytes.fromhex('04fafdff01010406000000'),
        bytes.fromhex('05fafd060403fbfa000000')
    ] 
    # payload format, all values are 1 byte: 
    # preset number | first slider value | second slider value | ... | 7th slider value | 3 null bytes
    # 50 | 100 | 400 | 1k | 2.5k | 6.3k | 16k (frequencies of sliders in order)
    # preset 3 has a 0x05 for byte number 8 but i dont know why

    HEARTBEAT = bytes.fromhex('28')

    def __init__(self, sock: bluetooth.BluetoothSocket):
        self.sock = sock
        self.incoming_queue = queue.Queue()
        self._stop_listener = threading.Event()
        self.listener_thread = threading.Thread(target=self._listener_loop, daemon=True)
        self.status_update_thread = threading.Thread(target=self._status_updater, daemon=True)
        self.status_update_thread.start()
        self.listener_thread.start()
        self._print_lock = threading.Lock()

        self.console = Console()
        self.live = Live(console=self.console, refresh_per_second=0.1)
        self.live.start()

    def _listener_loop(self):
        while not self._stop_listener.is_set():
            try:
                data = self.sock.recv(255)
                if data:
                    self.incoming_queue.put(data)
            except bluetooth.BluetoothError as e:
                print(f"[ERR] Bluetooth error in listener loop: {e}")
                break
            except Exception as e:
                print(f"[ERR] Unexpected error in listener loop: {e}")
                break
            time.sleep(0.01)
    
    def _get_next_message(self, timeout: int=None) -> bytes | None:
        try:
            return self.incoming_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def _stop_listener(self):
        self._stop_listener.set()
        self.listener_thread.join()

    def build_packet(self, sequence: bytes, command: bytes, payload: bytes) -> bytes:
        packet = bytearray()
        packet += sequence
        packet += command
        packet += bytes.fromhex("0100") # client ID
        packet += len(payload).to_bytes(1,'little')
        packet += payload
        return bytes(packet)

    def parse_packet(self, packet: bytes) -> Response:
        try:
            packet_array = packet
            payload_size = packet_array[4] #using an index to get an int back, slice to get bytes objects
            sequence = packet_array[0:1]
            command = packet_array[1:2]
            id = packet_array[2:3]
            payload = packet_array[5:5+payload_size]
            response = Response(sequence=sequence, command=command, id=id, payload_size=payload_size, payload=payload)
            return response
        except IndexError:
            return Response(error="Indexing error")

    def get_battery_bar(self, percent: int) -> str:
        filled_length = int(percent / 20)
        bar = "■" * filled_length + "-" * (5 - filled_length)
        return f"[{bar}] {percent}%"

    def print_battery_status(self, dev1: (str, int), dev2: (str, int), dev3: (str, int), name: str):
        table = Table(show_header=True, expand=True)

        table.add_column("Device", justify="center")
        table.add_column("Battery", justify="center")

        table.add_row(dev1[0], self.get_battery_bar(dev1[1]))
        table.add_row(dev2[0], self.get_battery_bar(dev2[1]))
        table.add_row(dev3[0], self.get_battery_bar(dev3[1]))
        
        return Panel(table, title=f"[bold]{name}[/bold]")

    def get_status(self, data: Payload)->(int, int, int):
        left = int.from_bytes(data.battery_l)
        right = int.from_bytes(data.battery_r)
        c_case = int.from_bytes(data.battery_case)

        return (left, right, c_case)

    def _status_updater(self):
        while not self._stop_listener.is_set():
            data = self._get_next_message(0.1)
            if data:
                packet = self.parse_packet(data)
                if packet.command == self.HEARTBEAT and packet.payload_size > 3:
                    battery_data = self._parse_heartbeat(packet)
                    left = battery_data.battery_l
                    right = battery_data.battery_r
                    with self._print_lock:
                        self.live.update(self.print_battery_status(("left", left),
                                                                ("right", right),
                                                                ("case", self.c_case),
                                                                self.device_name))
                elif packet.command == self.PAIR_COMMAND:
                    pairing_response = self.parse_pairing_response(packet)
                    if pairing_response.error == "wrong packet":
                        continue
                    self.paired = True
                    left, right, c_case = self.get_status(pairing_response)
                    self.c_case = c_case
                    self.device_name = pairing_response.name
                    with self._print_lock:
                        self.live.update(self.print_battery_status(("left", left),
                                                ("right", right),
                                                ("case", c_case),
                                                pairing_response.name))

    def _parse_heartbeat(self, packet: Response) -> Payload:
        if (packet.payload_size > 3):
            payload = packet.payload
            left = payload[2]
            right = payload[3]
            return Payload(left, right)
        else:
            return Payload(error="no battery data")

    def parse_pairing_response(self, payload: Response) -> Payload:
        try:
            if payload.payload_size > 14:
                payload = payload.payload
                name_length = payload[self.NAME_LENGTH_OFFSET] + 1
                battery_l = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][0:1])
                battery_r = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][1:2])
                battery_case = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][2:3])
                name = payload[self.NAME_OFFSET:self.NAME_OFFSET+name_length].decode('utf-8')
                response = Payload(battery_l, battery_r, battery_case, name)
                return response
            else:
                return Payload(error="wrong packet")
        except IndexError:
            return Payload(error="Indexing error")

    def _send_data(self, payload: bytes):
        self.sock.send(payload)

    def _pair(self, sequence: int) -> (str | None, int, Payload | None):
        print("[INF] Pairing with device...")
        
        steps = [self.PAIR_0, self.PAIR_1, self.PAIR_2]
        
        try:
            for i, step_cmd in enumerate(steps):
                payload = self.build_packet(int.to_bytes(sequence), self.PAIR_COMMAND, step_cmd)
                self._send_data(payload)
                data = self._get_next_message()

                '''if step_cmd == self.PAIR_1:
                    packet = self.parse_packet(data)
                    response = self.parse_pairing_response(packet)
                    if packet.error or response.error:
                        return (packet.error or response.error, sequence, None)
                    
                    pairing_info = response
                '''
                if step_cmd == self.PAIR_2:
                    data = self._get_next_message()
                    if not data:
                        return ("No data recieved", sequence, None)
                sequence += 1
            #print(f"[INF] Paired with {pairing_info.name} successfully!")
            return (None, sequence, 'Paired')#pairing_info)
        except Exception as e:
            return (f"Pairing failed {e}", sequence, None)

    def _toggle_feature(self, sequence: int, state: str, cmd_code: bytes, feature_name: str) -> (str | None, int, None):
        toggle_val = self.TOGGLE_ON if state == 'ON' else self.TOGGLE_OFF
        try:
            payload = self.build_packet(int.to_bytes(sequence), cmd_code, toggle_val)
            self._send_data(payload)
            data = self._get_next_message()
            packet = self.parse_packet(data)

            sequence += 1
            if packet.error:
                return (packet.error, sequence, None)
                
            return (None, sequence, None)
        
        except ConnectionError:
            return ("Connection error", sequence, None)

    def _bud_function_set(self, sequence: int, budstr: str, preset: str) -> (str | None, int, None):
        presets = {
            'control1': [self.NONE, self.PLAY_PAUSE, self.LAST_TRACK],
            'control2': [self.NONE, self.PLAY_PAUSE, self.NEXT_TRACK],
            'volume': [self.VOL_DOWN, self.VOL_UP, self.NONE],
            'none': [self.NONE, self.NONE, self.NONE]}
        BUD = {'left': self.LEFT_BUD, 'right': self.RIGHT_BUD}

        if preset == 'control':
            preset += '1' if budstr == 'left' else '2'
        bud = BUD.get(budstr)
        commands = presets.get(preset)
        
        if (commands and bud):
            for i, command in enumerate(commands):
                payload = bytearray()
                param = bud + self.TAP_AMNT[i]
                payload += param.to_bytes(1, 'little')
                payload += command
                packet = self.build_packet(int.to_bytes(sequence), self.EARBUD_FUNCTIONALITY_COMMAND, bytes(payload))
                self._send_data(packet)
                self._get_next_message()
                sequence += 1
            return (None, sequence, None)
        else:
            return ("Unknown preset/earbud", sequence, None)

    def _set_preset(self, sequence: int, preset: str)->(str | None, int, None):
        preset_dict = {
            'standard': 1,
            'heavybass': 2,
            'rock': 3,
            'jazz': 4,
            'vocal': 5
            }
        choice = preset_dict.get(preset)
        if choice:
            choice_payload = self.PRESETS[choice]
            packet = self.build_packet(int.to_bytes(sequence), self.SOUND_PROFILE_COMMAND, choice_payload)
            self._send_data(packet)
            self._get_next_message()
            sequence += 1
            return (None, sequence, None)
        else:
            return ('Selected preset does not exist.', sequence, None)

    def _exit(self):
        self._stop_listener()
        self.live.stop()


    def parse_command(self, command: str, sequence: int, *args)->(str | None, int, Payload | None):
        command_dict = {
            "exit": lambda *_: _exit,
            "pair": lambda seq, *a: self._pair(seq),
            "GM": lambda seq, *a: self._toggle_feature(seq, *a, self.GAME_MODE_COMMAND, "Game mode"),
            "Spatial": lambda seq, *a: self._toggle_feature(seq, *a, self.SPATIAL_AUDIO_COMMAND, "SpatialAudio"),
            "FN": self._bud_function_set,
            "SP": self._set_preset
            }
        if (command != 'pair' and self.paired == False):
            return ("You must pair with the device before doing that.", sequence, None) 
        
        func = command_dict.get(command)

        if func:
            try:
                return func(sequence, *args)
            except TypeError as e:
                return (f"Invalid arguments {e}", sequence, None)   
            except IndexError:
                return ("Missing arguments", sequence, None)   
            except Exception as e:
                return (str(e), sequence, None)
        else:
            return ("Unkown command", sequence, None)

def main():
    try:
        bd_addr = input("Enter MAC Address (XX:XX:XX:XX:XX:XX)>> ")
        port = 1

        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.connect((bd_addr, port))
        sock.settimeout(5.0)
        print(f"[INF] Connected to {bd_addr} on channel {port}")

        sequence = 0
        handler = ComHandler(sock)
        while True:
            if sequence == 16:
                sequence = 0
            command, *args = input(">> ").split(" ")
            err, sequence, response = handler.parse_command(command, sequence, *args)
            if (err):
                print(f"[ERR] {err}")
            '''elif response == 'Paired':
                handler.paired = True
                left, right, c_case = handler.get_status(response)
                handler.print_battery_status(("left", left), ("right", right), ("case", c_case))
                '''
        sock.close()
        print("Connection closed")

    except Exception as e:
        print(f"Error: {e}")

if (__name__ == "__main__"):
    main()
