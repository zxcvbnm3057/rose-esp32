from bridge.client import IoTAgentClient

client: IoTAgentClient = IoTAgentClient()
client.start()
client.wait_for_connection(timeout=60.0)
# uart_id = 0
# tx_gpio = 19  # UART0 TX
# rx_gpio = 20  # UART0 RX

# # Configure UART
# client.configure_uart(uart_id, baudrate=9600, tx_gpio=tx_gpio, rx_gpio=rx_gpio)

# # Test data
# test_data = bytes([0xfd, 0xf4, 0x01, 0xB6, 0x33, 0xA8, 0x60, 0xdf])

# # Send data
# client.send_uart(uart_id, test_data)

# # Read response (should receive the same data due to loopback)
# received = client.read_uart(uart_id, length=1)

# print(received)
uart_id = 1
tx_gpio = 12  # UART0 TX
rx_gpio = 13  # UART0 RX

listener = client.configure_uart(uart_id, baudrate=9600, tx_gpio=tx_gpio, rx_gpio=rx_gpio)
assert listener is not None

# Test data
test_data = bytes([0xfd, 0xf4, 0x01, 0xD3, 0xF4, 0xBB, 0x60, 0xdf])

# Send data
assert client.send_uart(uart_id, test_data)

received = listener.read(timeout=0.4)

print(received)