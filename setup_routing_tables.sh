# In this setup, there are three machines, the third machine runs a mahimahi shell with the outbox and the destination inside of it
# Sender --> Inbox --> [Mahimahi -> Outbox -> Destination]

# This script prints the commands necessary to setup the routing tables on three PD machines such that all
# traffic between $SRC and $DST will flow through $IN

# To use this script with a different cluster, change I10 and I192 to match the network interfaces

# SRC, IN, and DST are the PD machine #, and thus should be in the range [1.11] 
SRC=9
IN=10
DST=11

# Should not need to change below this line

I10=10.1.1.
I192=192.168.1.

# on S 
echo "==> Source Machine $I10$SRC"
echo "sudo ip route add $I10$DST via $I192$IN"
echo "sudo ethtool -K 10gp1 tso off gso off gro off"

# on I
echo "==> Inbox Machine $I10$IN"
echo "sudo sysctl net.ipv4.ip_forward=1"
echo "sudo ip route add $I10$DST dev 10gp1"
echo "sudo ip route add $I192$SRC dev em2"
echo "sudo ethtool -K 10gp1 tso off gso off gro off"

# on D
echo "==> Destination Machine $I10$DST"
echo "sudo ip route add $I192$SRC via $I10$IN"
echo "sudo ethtool -K 10gp1 tso off gso off gro off"
