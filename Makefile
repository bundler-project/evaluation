all: iperf/src/iperf \
	empirical-traffic-gen/bin/etgClient empirical-traffic-gen/bin/etgServer \
	bundler/target/debug/inbox bundler/target/debug/outbox

iperf/src/iperf:
	cd iperf && ./autogen.sh && ./configure
	make -C iperf

empirical-traffic-gen/bin/etgClient empirical-traffic-gen/bin/etgServer:
	make -C empirical-traffic-gen

bundler/target/debug/inbox bundler/target/debug/outbox:
	cd bundler && git submodule update --init --recursive
	cd bundler && cargo build
