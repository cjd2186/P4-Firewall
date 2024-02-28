#!/usr/bin/env python3
import argparse
import os
import sys
import threading
import socket
from time import sleep

import grpc

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 './utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

SWITCH_TO_HOST_PORT = 1
SWITCH_TO_SWITCH_PORT = 2

# define color for printing on console
CRED = '\033[91m'
CEND = '\033[0m'
CGREEN = '\033[32m'

s1_connection_metadata = {
    "h1": {
        "dst_eth_addr": "08:00:00:00:01:11",
        "dst_ipv4_addr": "10.0.1.1",
        "port": 1
    },
    "h2": {
        "dst_eth_addr": "08:00:00:00:02:22",
        "dst_ipv4_addr": "10.0.2.2",
        "port": 2
    },
    "h3": {
        "dst_eth_addr": "08:00:00:00:03:33",
        "dst_ipv4_addr": "10.0.3.3",
        "port": 3
    }
}

def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.
    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print('\n----- Reading tables rules for %s -----' % sw.name)
    data_table = []

    for response in sw.ReadTableEntries():
        for entity in response.entities:
            cur_table = []

            entry = entity.table_entry

            table_name = p4info_helper.get_tables_name(entry.table_id)
            for m in entry.match:

                ipv4_dst_addr, ipv4_port = p4info_helper.get_match_field_value(m)
                if ipv4_dst_addr == b'\n\x00\x01\x01':
                    cur_table  += ["h1", s1_connection_metadata["h1"]["dst_eth_addr"], s1_connection_metadata["h1"]["dst_ipv4_addr"], s1_connection_metadata["h1"]["port"]]
                if ipv4_dst_addr == b'\n\x00\x02\x02':
                    cur_table += ["h2", s1_connection_metadata["h2"]["dst_eth_addr"], s1_connection_metadata["h2"]["dst_ipv4_addr"], s1_connection_metadata["h2"]["port"]]
                if ipv4_dst_addr == b'\n\x00\x03\x03':
                    cur_table += ["h3", s1_connection_metadata["h3"]["dst_eth_addr"], s1_connection_metadata["h3"]["dst_ipv4_addr"], s1_connection_metadata["h3"]["port"]]

            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)

            if action_name == "MyIngress.ipv4_forward":
                cur_table.append(CGREEN+"connected"+CEND)
            if action_name == "MyIngress.drop":
                cur_table.append(CRED+"disconnected"+CEND)
            data_table.append(cur_table)

    # print in table format
    print("switch", "dst_eth_addr", "dst_ipv4_addr", "port", "connection")
    for switch, dst_eth_addr, dst_ipv4, port, connection in data_table:
        print(switch, dst_eth_addr, dst_ipv4, port, connection)
    print()

def printCounter(p4info_helper, sw, counter_name, index):
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print("%s %s %d: %d packets (%d bytes)" % (
                sw.name, counter_name, index,
                counter.data.packet_count, counter.data.byte_count
            ))

def writeTableRules(p4info_helper, ingress_sw, dst_eth_addr, dst_ip_addr, port, dst_id):

    # Write ingress rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": port,
            "dst_id": dst_id
        }
    )
    ingress_sw.WriteTableEntry(table_entry)

def blockTableEntry(p4info_helper, ingress_sw, dst_eth_addr, dst_ip_addr, port, dst_id):
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": port,
            "dst_id": dst_id
        }
    )
    ingress_sw.DeleteTableEntry(table_entry, False)

    # Change to drop func
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.drop"
    )
    ingress_sw.WriteTableEntry(table_entry)

def listen_from_sender(p4info_helper, ingress_sw, block_switch_info):
    UDPServerSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    UDPServerSocket.bind(("127.0.0.1", 20001))
    while True:
        bytesAddressPair = UDPServerSocket.recvfrom(1024)
        if bytesAddressPair[0] == b'1':
            blockTableEntry(p4info_helper, ingress_sw, block_switch_info["dst_eth_addr"], block_switch_info["dst_ip_addr"], block_switch_info["port"], block_switch_info["dst_id"])
            print(CRED+ingress_sw.name+" disconnects "+" s2"+CEND)
            break

def print_table(p4info_helper, sw):
    while True:
        sleep(2)
        readTableRules(p4info_helper, sw)

def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
        name='s1',
        address='127.0.0.1:50051',
        device_id=0,
        proto_dump_file='logs/s1-p4runtime-requests.txt')
    s2 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
        name='s2',
        address='127.0.0.1:50052',
        device_id=1,
        proto_dump_file='logs/s2-p4runtime-requests.txt')
    s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
        name='s3',
        address='127.0.0.1:50053',
        device_id=2,
        proto_dump_file='logs/s3-p4runtime-requests.txt')

    s1.MasterArbitrationUpdate()
    s2.MasterArbitrationUpdate()
    s3.MasterArbitrationUpdate()

    s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info, bmv2_json_file_path=bmv2_file_path)
    s2.SetForwardingPipelineConfig(p4info=p4info_helper.p4info, bmv2_json_file_path=bmv2_file_path)
    s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info, bmv2_json_file_path=bmv2_file_path)

    # setup the connection for s1
    writeTableRules(p4info_helper, ingress_sw=s1, dst_eth_addr="08:00:00:00:01:11", dst_ip_addr="10.0.1.1", port=1, dst_id=100)
    writeTableRules(p4info_helper, ingress_sw=s1, dst_eth_addr="08:00:00:00:02:22", dst_ip_addr="10.0.2.2", port=2, dst_id=200)
    writeTableRules(p4info_helper, ingress_sw=s1, dst_eth_addr="08:00:00:00:03:33", dst_ip_addr="10.0.3.3", port=3, dst_id=300)

    # setup the connection for s2
    writeTableRules(p4info_helper, ingress_sw=s2, dst_eth_addr="08:00:00:00:01:11", dst_ip_addr="10.0.1.1", port=1, dst_id=400)
    writeTableRules(p4info_helper, ingress_sw=s2, dst_eth_addr="08:00:00:00:02:22", dst_ip_addr="10.0.2.2", port=2, dst_id=500)
    writeTableRules(p4info_helper, ingress_sw=s2, dst_eth_addr="08:00:00:00:03:33", dst_ip_addr="10.0.3.3", port=3, dst_id=600)

    # setup the connection for s3
    writeTableRules(p4info_helper, ingress_sw=s3, dst_eth_addr="08:00:00:00:01:11", dst_ip_addr="10.0.1.1", port=1, dst_id=700)
    writeTableRules(p4info_helper, ingress_sw=s3, dst_eth_addr="08:00:00:00:02:22", dst_ip_addr="10.0.2.2", port=2, dst_id=800)
    writeTableRules(p4info_helper, ingress_sw=s3, dst_eth_addr="08:00:00:00:03:33", dst_ip_addr="10.0.3.3", port=3, dst_id=900)

    block_switch_info = {
        "dst_eth_addr": s1_connection_metadata["h2"]["dst_eth_addr"],
        "dst_ip_addr": s1_connection_metadata["h2"]["dst_ipv4_addr"],
        "port": s1_connection_metadata["h2"]["port"],
        "dst_id": 200

    }
    t1 = threading.Thread(target=listen_from_sender, args=(p4info_helper, s1, block_switch_info))
    t2 = threading.Thread(target=print_table, args=(p4info_helper, s1))
    t1.start()
    t2.start()

    t1.join()
    t2.join()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/basic.p4.p4info.txt')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/basic.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print("\np4info file not found: %s\nHave you run 'make'?" % args.p4info)
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print("\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json)
        parser.exit(1)
    main(args.p4info, args.bmv2_json)
