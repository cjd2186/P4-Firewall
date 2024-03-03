# P4-Firewall
P4 Firewall from research in Columbia's Internet Real Time Lab: a white-list only firewall of IoT Devices

In this repository, I built upon the exisiting codebase of the lab's P4 Firewall project.
My contributions lie in the following files:
* controller.py
* basic.p4

Where I created a blacklist routine for the firewall. This routine would block ip addresses when the traffic received from these IoT devices containaed abnormally large packet sizes, or if the rate at which these packets were received were abnormal as well. Both of these rules monitor live traffic sent to and received at the firewall.
