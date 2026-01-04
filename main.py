import bluetooth
from dataclasses import dataclass
import inspect

@dataclass
class Response:
    sequence: bytes | None
    command: bytes | None
    id: bytes | None
    payload: bytearray | None
    error: str | None = None

@dataclass
class Payload:
    battery_l: bytes | None
    battery_r: bytes | None
    battery_case: bytes | None
    name: str | None
    error: str | None = None

class ComHandler:
    paired = False

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
    
    # 0101 unknown
    # 0102 unknown
    # either my packet capture wasn't as thorough as I'd like or those values don't correspond to my specific device

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
            packet_array = bytearray(packet)
            payload_size = packet_array[4]
            sequence = bytes(packet_array[0])
            command = bytes(packet_array[1])
            id = bytes(packet_array[2])
            payload = packet_array[5:5+payload_size]
            response = Response(sequence, command, id, payload)
            return response
        except IndexError:
            return Response(error="Indexing error")

    def parse_pairing_response(self, payload: Response) -> Payload:
        try:
            payload = payload.payload
            name_length = payload[self.NAME_LENGTH_OFFSET] + 1
            battery_l = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][0:1])
            battery_r = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][1:2])
            battery_case = bytes(payload[self.BATTERY_INDEX:self.BATTERY_OFFSET][2:3])
            name = payload[self.NAME_OFFSET:self.NAME_OFFSET+name_length].decode('utf-8')
            response = Payload(battery_l, battery_r, battery_case, name)
            return response
        except IndexError:
            return Response(error="Indexing error")

    def _send_and_recieve(self, socket: bluetooth.BluetoothSocket, payload: bytes) -> bytes:
        socket.send(payload)
        data = socket.recv(255)
        if not data:
            raise ConnectionError(f"No response recieved during exchange")
        return data

    def _pair(self, socket: bluetooth.BluetoothSocket, sequence: int) -> (str | None, int, Response | None):
        print("[INF] Pairing with device...")
        
        steps = [self.PAIR_0, self.PAIR_1, self.PAIR_2]
        
        try:
            for i, step_cmd in enumerate(steps):
                payload = self.build_packet(int.to_bytes(sequence), self.PAIR_COMMAND, step_cmd)
                data = self._send_and_recieve(socket, payload)
                
                if step_cmd == self.PAIR_1:
                    packet = self.parse_packet(data)
                    response = self.parse_pairing_response(packet)
                    
                    if packet.error or response.error:
                        return (packet.error or response.error, sequence, None)
                    
                    pairing_info = response
                
                if step_cmd == self.PAIR_2:
                    data = socket.recv(255)
                    if not data:
                        return ("No data recieved", sequence, None)
                sequence += 1
            print(f"[INF] Paired with {pairing_info.name} successfully!")
            return (None, sequence, pairing_info)
        except Exception as e:
            return (f"Pairing failed {e}", sequence, None)

    def _toggle_feature(self, socket: bluetooth.BluetoothSocket, sequence: int, state: str, cmd_code: bytes, feature_name: str) -> (str | None, int, None):
        toggle_val = self.TOGGLE_ON if state == 'ON' else self.TOGGLE_OFF
        try:
            payload = self.build_packet(int.to_bytes(sequence), cmd_code, toggle_val)
            data = self._send_and_recieve(socket, payload)
            packet = self.parse_packet(data)

            sequence += 1
            if packet.error:
                return (packet.error, sequence, None)
                
            return (None, sequence, None)
        
        except ConnectionError:
            return ("Connection error", sequence, None)

    def _bud_function_set(self, socket: bluetooth.BluetoothSocket, sequence, budstr: str, preset: str) -> (str | None, int, None):
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
                data = self._send_and_recieve(socket, packet)
                sequence += 1
            return (None, sequence, None)
        else:
            return ("Unknown preset/earbud", sequence, None)

    def parse_command(self, command: str, socket: bluetooth.BluetoothSocket, sequence: int, *args)->(str | None, int, Response | None):
        command_dict = {
            "exit": lambda *_: exit(),
            "pair": lambda s, seq, *a: self._pair(s, seq),
            "GM": lambda s, seq, *a: self._toggle_feature(s, seq, *a, self.GAME_MODE_COMMAND, "Game mode"),
            "Spatial": lambda s, seq, *a: self._toggle_feature(s, seq, *a, self.SPATIAL_AUDIO_COMMAND, "SpatialAudio"),
            "FN": self._bud_function_set
            }
        if (command != 'pair' and self.paired == False):
            return ("You must pair with the device before doing that.", sequence, None) 
        
        func = command_dict.get(command)

        if func:
            try:
                return func(socket, sequence, *args)
            except TypeError as e:
                return (f"Invalid arguments {e}", sequence, None)   
            except IndexError:
                return ("Missing arguments", sequence, None)   
            except Exception as e:
                return (str(e), sequence, None)
        else:
            return ("Unkown command", sequence, None)


def get_battery_bar(percent: int) -> str:
    filled_length = int(percent / 20)
    bar = "■" * filled_length + "-" * (5 - filled_length)
    return f"[{bar}] {percent}%"

def print_battery_status(dev1: (str, int), dev2: (str, int), dev3: (str, int)):
    line = (
        f"{dev1[0]:<10} {get_battery_bar(dev1[1])}    |    "
        f"{dev2[0]:<10} {get_battery_bar(dev2[1])}    |    "
        f"{dev3[0]:<10} {get_battery_bar(dev3[1])}"
    )
    
    print("-" * len(line))
    print(line)
    print("-" * len(line))

def main():
    try:
        bd_addr = input("Enter MAC Address (XX:XX:XX:XX:XX:XX)>> ")
        port = 1

        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.connect((bd_addr, port))
        sock.settimeout(2.0)
        print(f"[INF] Connected to {bd_addr} on channel {port}")

        sequence = 0
        handler = ComHandler()
        while True:
            if sequence == 16:
                sequence = 0
            command, *args = input(">> ").split(" ")
            err, sequence, response = handler.parse_command(command, sock, sequence, *args)
            if (err):
                print(f"[ERR] {err}")
            elif response:
                handler.paired = True
                left = int.from_bytes(response.battery_l)
                right = int.from_bytes(response.battery_r)
                c_case = int.from_bytes(response.battery_case)
                print_battery_status(("left", left), ("right", right), ("case", c_case))

        sock.close()
        print("Connection closed")

    except Exception as e:
        print(f"Error: {e}")

if (__name__ == "__main__"):
    main()
