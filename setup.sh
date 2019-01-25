sudo apt-get update
# inbox deps
sudo apt-get install libnl-3-dev libnl-genl-3-dev libnl-nf-3-dev libnl-route-3-dev libnfnetlink-dev autoconf autotools-dev libpcap-dev
# qdisc deps
sudo apt-get install libelf-dev

curl https://sh.rustup.rs -sSf | sh
source $HOME/.cargo/env
rustup default nightly
rustup component add rust-src

git clone git@github.mit.edu:akshayn/bundler.git
cd bundler
git submodule update --init --recursive

# build qdisc
cd qdisc
./build_tc.sh 
make QTYPE=sfq

# build boxes
cd ..
cd box
cargo build --release

cd ~/
git clone https://github.com/akshayknarayan/ccp_copa.git
cd ccp_copa
git checkout rate_only
cargo build --release

cd ~/
git clone https://github.com/ccp-project/bbr.git
cd bbr
git checkout update
cargo build --release

cd ~/
git clone https://github.com/ccp-project/nimbus.git
cd nimbus
git checkout null-xtcp
cargo build --release
