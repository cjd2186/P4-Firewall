import argparse
import socket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_addr', type=str, help="The destination IP address to use")
    args = parser.parse_args()

    addr = socket.gethostbyname(args.ip_addr)

    # send a signal to p4runtime to blockTableEntry for h2
    if addr == "10.0.2.2":
        UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        UDPClientSocket.sendto(b'1', ("127.0.0.1", 20001))

if __name__ == "__main__":
    main()
