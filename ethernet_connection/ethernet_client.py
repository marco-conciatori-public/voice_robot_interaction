import time
import socket
import threading

import args
import global_constants as gc

class EthernetClient:
    def __init__(self, shared_variable_manager, **kwargs):
        """
        Initializes the Ethernet client with the specified host and port.
        :param shared_variable_manager: instance of SharedVariableManager to manage shared variables.
        :param host: The hostname or IP address of the server to connect to.
        :param port: The port number on which the server is listening.
        """
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'ethernet_client.yaml', **kwargs)
        self.shared_variable_manager = shared_variable_manager
        self.host = parameters['host']
        self.port = parameters['port']
        self.socket = None

    def connect(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        print(f"Connected to server {self.host}:{self.port}")

    def send_data(self, data) -> None:
        try:
            self.socket.sendall(data.encode())
            print(f"Client sent: {data}")
        except Exception as e:
            print(f'Error in ethernet client send_data:\n\t{e}\n\t{e.__traceback__}')

    def receive_data(self):
        try:
            data = self.socket.recv(1024)
            if not data:
                print("No data received.")
                return None
            print(f"Client received: {data.decode()}")
            return data.decode()
        except Exception as e:
            print(f'Error in ethernet client receive_data:\n\t{e}\n\t{e.__traceback__}')

    def close(self) -> None:
        if self.socket:
            self.socket.close()
            print("Connection closed.")

    def receiver(self) :
        if self.socket:
            while True:
                decoded_data = self.receive_data()
                if decoded_data is not None:
                    self.shared_variable_manager.add_to(queue_name='received_ethernet_data', value=decoded_data)
                else:
                    time.sleep(0.3)

    def sender(self):
        if self.socket:
            counter = 0
            while True:
                time.sleep(5)
                message_to_send = f'Message {counter} from client'
                counter += 1
                # message_to_send = self.shared_variable_manager.pop_from(queue_name='functions_to_call')
                if message_to_send is None:
                    time.sleep(0.3)
                    continue
                else:
                    self.send_data(message_to_send)
                    time.sleep(0.01)

    def start(self):
        self.connect()
        # Start the receiver and sender threads
        print('Starting Ethernet client threads...')
        receiver_thread = threading.Thread(target=self.receiver, name='ethernet_client_receiver')
        sender_thread = threading.Thread(target=self.sender, name='ethernet_client_sender')

        receiver_thread.start()
        print(f'Receiver thread started: "{receiver_thread.name}"')
        sender_thread.start()
        print(f'Sender thread started: "{sender_thread.name}"')

        # Keep the main thread alive or join the other threads
        receiver_thread.join()
        sender_thread.join()

        self.close()


if __name__ == "__main__":
    from thread_shared_variables import SharedVariableManager

    shared_variable_manager = SharedVariableManager(verbose=2)
    ethernet_client = EthernetClient(shared_variable_manager=shared_variable_manager)
    ethernet_client.start()
