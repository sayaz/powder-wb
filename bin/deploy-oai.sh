set -ex
COMMIT_HASH=$1
NODE_ROLE=$2
BINDIR=`dirname $0`
ETCDIR=/local/repository/etc
source $BINDIR/common.sh

if [ -f $SRCDIR/oai-setup-complete ]; then
    echo "setup already ran; not running again"
    if [ $NODE_ROLE == "cn" ]; then
        sudo sysctl net.ipv4.conf.all.forwarding=1
        sudo iptables -P FORWARD ACCEPT
    elif [ $NODE_ROLE == "nodeb" ]; then
        LANIF=`ip r | awk '/192\.168\.1\.2/{print $3}'`
        if [ ! -z $LANIF ]; then
          echo LAN IFACE is $LANIF...
          echo adding route to CN
          sudo ip route add 192.168.70.128/26 via 192.168.1.1 dev $LANIF
        fi
    fi
    exit 0
fi

function setup_cn_node {
    # Install docker, docker compose, wireshark/tshark
    echo setting up cn node
    sudo apt-get update && sudo apt-get install -y \
      apt-transport-https \
      ca-certificates \
      curl \
      gnupg \
      lsb-release

    printf "adding docker gpg key"
    until curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -; do
        printf '.'
        sleep 2
    done

    sudo add-apt-repository -y "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    sudo add-apt-repository -y ppa:wireshark-dev/stable
    echo "wireshark-common wireshark-common/install-setuid boolean false" | sudo debconf-set-selections

    sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo apt-get install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        wireshark \
        tshark

    sudo systemctl enable docker
    sudo usermod -aG docker $USER

    printf "installing compose"
    until sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose; do
        printf '.'
        sleep 2
    done

    sudo chmod +x /usr/local/bin/docker-compose

    echo creating demo-oai bridge network...
    sudo docker network create \
      --driver=bridge \
      --subnet=192.168.70.128/26 \
      -o "com.docker.network.bridge.name"="demo-oai" \
      demo-oai-public-net
    echo creating demo-oai bridge network... done.

    echo pulling cn5g images...
    sudo docker pull ubuntu:bionic
    sudo docker pull mysql:8.0
    sudo docker pull oaisoftwarealliance/oai-amf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-nrf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-spgwu-tiny:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-smf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-udr:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-udm:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-ausf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-upf-vpp:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-nssf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-pcf:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/oai-nef:$COMMIT_HASH
    sudo docker pull oaisoftwarealliance/trf-gen-cn5g:latest

    echo pulling cn5g images... done.

    sudo sysctl net.ipv4.conf.all.forwarding=1
    sudo iptables -P FORWARD ACCEPT

    echo cloning and syncing oai-cn5g-fed...
    cd $SRCDIR
    git clone --branch $COMMIT_HASH $OAI_CN5G_REPO oai-cn5g-fed
    cd oai-cn5g-fed
    git checkout -f $COMMIT_HASH
    ./scripts/syncComponents.sh
    echo cloning and syncing oai-cn5g-fed... done.

    echo replacing a couple of configuration files
    cp /local/repository/etc/oai/docker-compose-mini-nrf.yaml /var/tmp/oai-cn5g-fed/docker-compose/docker-compose-mini-nrf.yaml
    cp /local/repository/etc/oai/oai_db1.sql /var/tmp/oai-cn5g-fed/docker-compose/database/oai_db1.sql
    echo setting up cn node... done.

}

function setup_ran_node {
    # using `build-oai -I --install-optional-packages` results in interactive
    # prompts, so...
    echo installing supporting packages...
    sudo add-apt-repository -y ppa:ettusresearch/uhd
    sudo apt update && sudo apt install -y \
        iperf3 \
        libboost-dev \
        libforms-dev \
        libforms-bin \
        libuhd-dev \
        numactl \
        uhd-host \
        zlib1g \
        zlib1g-dev
    sudo uhd_images_downloader
    echo installing supporting packages... done.

    echo cloning and building oai ran...
    cd $SRCDIR
    git clone $OAI_RAN_MIRROR oairan
    cd oairan
    git checkout $COMMIT_HASH

    source oaienv
    cd cmake_targets

    ./build_oai -I --ninja
    ./build_oai -w USRP \
        --build-lib telnetsrv \
        --build-lib nrscope \
        $BUILD_ARGS --ninja
    echo cloning and building oai ran... done.
}

function configure_nodeb {
    echo configuring nodeb...
    mkdir -p $SRCDIR/etc/oai
    cp -r $ETCDIR/oai/* $SRCDIR/etc/oai/
    LANIF=`ip r | awk '/192\.168\.1\.0/{print $3}'`
    if [ ! -z $LANIF ]; then
      LANIP=`ip r | awk '/192\.168\.1\.0/{print $NF}'`
      echo LAN IFACE is $LANIF IP is $LANIP.. updating nodeb config
      find $SRCDIR/etc/oai/ -type f -exec sed -i "s/LANIF/$LANIF/" {} \;
      echo adding route to CN
      sudo ip route add 192.168.70.128/26 via 192.168.1.1 dev $LANIF
    else
      echo No LAN IFACE.. not updating nodeb config
    fi
    echo configuring nodeb... done.
}

function configure_ue {
    echo configuring ue...
    mkdir -p $SRCDIR/etc/oai
    cp -r $ETCDIR/oai/* $SRCDIR/etc/oai/
    echo configuring ue... done.
}

if [ $NODE_ROLE == "cn" ]; then
    setup_cn_node
elif [ $NODE_ROLE == "nodeb" ]; then
    BUILD_ARGS="--gNB"
    setup_ran_node
    configure_nodeb
elif [ $NODE_ROLE == "ue" ]; then
    BUILD_ARGS="--nrUE"
    setup_ran_node
    configure_ue
fi



touch $SRCDIR/oai-setup-complete
