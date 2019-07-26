all: iperf/src/iperf \
	empirical-traffic-gen/bin/etgClient empirical-traffic-gen/bin/etgServer \
	bundler/target/debug/inbox bundler/target/debug/outbox \
	mahimahi/src/frontend/mm-delay mahimahi/src/frontend/mm-link

iperf/src/iperf: iperf/src/*.c
	cd iperf && ./autogen.sh && ./configure
	make -C iperf

empirical-traffic-gen/bin/etgClient empirical-traffic-gen/bin/etgServer: empirical-traffic-gen/src/*.c
	make -C empirical-traffic-gen

bundler/target/debug/inbox bundler/target/debug/outbox:
	sudo apt update && sudo apt install \
		llvm llvm-dev clang libclang-dev \
		libnl-3-dev libnl-genl-3-dev libnl-route-3-dev libnfnetlink-dev \
		bison flex libpcap-dev
	cd bundler && git submodule update --init --recursive
	cd bundler && cargo build

mahimahi/src/frontend/mm-delay mahimahi/src/frontend/mm-link: $(shell find mahimahi -name "*.cc")
	sudo apt update && sudo apt install \
		protobuf-compiler libprotobuf-dev autotools-dev dh-autoreconf \
		iptables pkg-config dnsmasq-base apache2-bin apache2-dev \
		debhelper libssl-dev ssl-cert libxcb-present-dev libcairo2-dev libpango1.0-dev
	cd mahimahi && ./autogen.sh && ./configure
	cd mahimahi && make -j && sudo make install
