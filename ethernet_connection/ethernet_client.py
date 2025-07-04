import json
import time
import socket
import threading

import args
import utils
import global_constants as gc


class EthernetClient:
    def __init__(self, shared_variable_manager, **kwargs):
        """
        Initializes the Ethernet client with the specified host and port.
        :param shared_variable_manager: instance of SharedVariableManager to manage shared variables.
        :param host: The hostname or IP address of the server to connect to.
        :param port: The port number on which the server is listening.
        :param retry_interval: Time in seconds to wait before retrying connection if it fails.
        :param verbose: Verbosity level for logging.
        """
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'ethernet_client.yaml', **kwargs)
        self.shared_variable_manager = shared_variable_manager
        self.host = parameters['host']
        self.port = parameters['port']
        self.retry_interval = parameters['retry_interval']
        self.verbose = parameters['verbose']
        self.socket = None

    def connect(self) -> None:
        connection_established = False
        if self.verbose >= 2:
            print('Starting Ethernet client...')
        while not connection_established:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                if self.verbose >= 1:
                    print(f'\tConnected to server {self.host}:{self.port}')
                connection_established = True
            except socket.error as e:
                utils.print_exception(exception=e, message='Error connecting to server')
                if self.verbose >= 1:
                    print(f'\tConnection failed. Retrying in {self.retry_interval} seconds...')
                connection_established = False
            time.sleep(self.retry_interval)
            # TODO: this could be blocking the main thread?

    def send_data(self, data) -> None:
        try:
            self.socket.sendall(data.encode())
            if self.verbose >= 3:
                print(f'Client sent: {data}')
        except Exception as e:
            utils.print_exception(exception=e, message='Error in ethernet client send_data')
            self.close()

    def send_function_call(self, function_call) -> None:
        """
        Sends a function call to the server.
        :param function_call: The function call to send, which should be a string representation.
        """
        try:
            # Convert the FunctionCall object to a dictionary
            # The 'name' attribute is a string, 'args' is a dictionary
            # Adjust based on the exact structure if it differs slightly
            data_to_send = {
                'name': function_call.name,
                'args': function_call.args,
            }
            if self.verbose >= 3:
                print(f'Sending function call: {data_to_send}')
            # Serialize the dictionary to a JSON string
            json_string = json.dumps(data_to_send)
            # Encode the JSON string to bytes (e.g., UTF-8)
            message_to_send = json_string.encode('utf-8')
            # Send the length of the message first (important for reliable reception)
            # This is important for the receiver to know how much data to expect for one message.
            length_prefix = len(message_to_send).to_bytes(length=4, byteorder='big')  # 4 bytes, big-endian
            self.socket.sendall(length_prefix + message_to_send)
        except Exception as e:
            utils.print_exception(exception=e, message='Error in ethernet client send_function_call')
            self.close()

    def receive_data(self) -> str:
        try:
            data = self.socket.recv(1024)
            if not data:
                if self.verbose >= 2:
                    print('No data received from server.')
                self.close()
            return data.decode()
        except Exception as e:
            utils.print_exception(exception=e, message='Error in ethernet client receive_data')
            self.close()

    def close(self) -> None:
        if self.socket:
            self.socket.close()
            if self.verbose >= 1:
                print(f'Connection to {self.host}:{self.port} closed.')
            self.socket = None
            #

    def sender(self):
        while self.socket:
            message_to_send = self.shared_variable_manager.pop_from(queue_name='functions_to_call')
            if message_to_send is None:
                time.sleep(0.3)
                continue
            else:
                self.send_function_call(message_to_send)
                time.sleep(0.01)

    def receiver(self) :
        while self.socket:
            decoded_data = self.receive_data()
            if decoded_data is not None:
                self.shared_variable_manager.add_to(queue_name='received_ethernet_data', value=decoded_data)
            else:
                time.sleep(0.3)

    def start(self):
        self.connect()
        # Start the receiver and sender threads
        receiver_thread = threading.Thread(target=self.receiver, name='ethernet_client_receiver')
        sender_thread = threading.Thread(target=self.sender, name='ethernet_client_sender')

        receiver_thread.start()
        if self.verbose >= 1:
            print(f'Receiver thread started: "{receiver_thread.name}"')
        sender_thread.start()
        if self.verbose >= 1:
            print(f'Sender thread started: "{sender_thread.name}"')

        receiver_thread.join()
        if self.verbose >= 1:
            print('receiver thread ended.')
        sender_thread.join()
        if self.verbose >= 1:
            print('sender thread ended.')
        self.close()
        if self.verbose >= 1:
            print('Ethernet client stopped.')
