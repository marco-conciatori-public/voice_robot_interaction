import time
import socket
import warnings
import threading

import args
import utils
import global_constants as gc
from robot_link import protocol


class EthernetClient:
    def __init__(self, shared_variable_manager, command_handlers: dict = None, **kwargs):
        """
        TCP client for the bidirectional JSON command channel to the RDK X3.

        Outgoing (Jetson -> RDK X3): function calls queued in 'functions_to_call' (e.g. arm moves
        produced by the voice interaction) are sent as JSON commands.
        Incoming (RDK X3 -> Jetson): JSON commands are dispatched to local handlers, e.g. the
        headlight controls. Unknown commands are logged and ignored.

        :param shared_variable_manager: instance of SharedVariableManager to manage shared variables.
        :param command_handlers: optional dict {command_name: callable} for commands received from the
            RDK X3.
        :param host: The hostname or IP address of the server to connect to.
        :param port: The port number on which the server is listening.
        :param retry_interval: Time in seconds to wait before retrying connection if it fails.
        :param verbose: Verbosity level for logging.
        """
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'ethernet_client.yaml', **kwargs)
        self.shared_variable_manager = shared_variable_manager
        self.command_handlers = command_handlers if command_handlers is not None else {}
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

    def send_function_call(self, function_call) -> None:
        """
        Sends a function call to the server as a JSON command (name + args).
        :param function_call: object exposing .name (str) and .args (dict).
        """
        try:
            if self.verbose >= 3:
                print(f'Sending function call: {function_call.name} {function_call.args}')
            protocol.send_command(self.socket, function_call.name, function_call.args)
        except Exception as e:
            utils.print_exception(exception=e, message='Error in ethernet client send_function_call')
            self.close()

    def _dispatch(self, command: dict) -> None:
        """Execute a command received from the RDK X3 via its local handler."""
        name = command.get('name')
        command_args = command.get('args')
        handler = self.command_handlers.get(name)
        if handler is None:
            warnings.warn(f'No handler for command "{name}" received from the RDK X3.')
            return
        if self.verbose >= 3:
            print(f'Executing command from RDK X3: {name} {command_args}')
        try:
            if command_args:
                handler(**command_args)
            else:
                handler()
        except Exception as e:
            utils.print_exception(exception=e, message=f'Error executing command "{name}"')

    def close(self) -> None:
        if self.socket:
            self.socket.close()
            if self.verbose >= 1:
                print(f'Connection to {self.host}:{self.port} closed.')
            self.socket = None

    def sender(self):
        while self.socket:
            message_to_send = self.shared_variable_manager.pop_from(queue_name='functions_to_call')
            if message_to_send is None:
                time.sleep(0.3)
                continue
            else:
                self.send_function_call(message_to_send)
                time.sleep(0.01)

    def receiver(self):
        while self.socket:
            command = protocol.recv_command(self.socket)
            if command is None:
                # the RDK X3 closed the connection (or framed an empty message)
                self.close()
                break
            self._dispatch(command)

    def start(self):
        self.connect()
        # Start the receiver and sender threads (the channel is full-duplex on one socket)
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
