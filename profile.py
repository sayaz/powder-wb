#!/usr/bin/env python

import os
import geni.portal as portal
import geni.rspec.pg as rspec
import geni.rspec.igext as IG
import geni.rspec.emulab.pnext as PN


tourDescription = """
### OAI 5G on POWDER Paired Radio Workbench

"""

tourInstructions = """

Startup scripts will still be running after your experiment becomes ready. Watch
the "Startup" column on the "List View" tab for your experiment and wait until
all of the compute nodes show "Finished" before proceeding.

After all startup scripts have finished...

On `cn`:

If you'd like to monitor traffic between the various network functions and the
gNodeB, start tshark in a session:

```
sudo tshark -i demo-oai \
  -f "not arp and not port 53 and not host archive.ubuntu.com and not host security.ubuntu.com"
```

In another session, start the 5G core network services. It will take several
seconds for the services to start up. Make sure the script indicates that the
services are healthy before moving on.

```
cd /var/tmp/oai-cn5g-fed/docker-compose
sudo python3 ./core-network.py --type start-mini --scenario 1
```

In yet another session, start following the logs for the AMF. This way you can
see when the UE syncs with the network.

```
sudo docker logs -f oai-amf
```

On `nodeb`:

```
sudo numactl --membind=0 --cpubind=0 \
  /var/tmp/oairan/cmake_targets/ran_build/build/nr-softmodem -E \
  -O /var/tmp/etc/oai/gnb.sa.band78.fr1.106PRB.usrpx310.conf --sa \
  --MACRLCs.[0].dl_max_mcs 28 --tune-offset 23040000
```

On `ue`:

After you've started the gNodeB, start the UE:

```
sudo numactl --membind=0 --cpubind=0 \
  /var/tmp/oairan/cmake_targets/ran_build/build/nr-uesoftmodem -E \
  -O /var/tmp/etc/oai/ue.conf \
  -r 106 \
  -C 3619200000 \
  --usrp-args "clock_source=external,type=x300" \
  --band 78 \
  --numerology 1 \
  --ue-txgain 0 \
  --ue-rxgain 104 \
  --nokrnmod \
  --dlsch-parallel 4 \
  --sa
```

After the UE associates, open another session check the UE IP address.

```
# check UE IP address
ifconfig oaitun_ue1

# add a route toward the CN traffic gen node
sudo ip route add 192.168.70.0/24 dev oaitun_ue1
```

You should now be able to generate traffic in either direction:

```
# from UE to CN traffic gen node (in session on ue node)
ping 192.168.70.135

# from CN traffic generation service to UE (in session on cn node)
sudo docker exec -it oai-ext-dn ping <UE IP address>
```

Known Issues:

- The gNodeB and nrUE soft-modems may spam warnings/errors about missed DCI or
  ULSCH detections. They may crash unexpectedly.

- Exiting the OAI RAN processes with ctrl-c will often leave the SDR in a funny
  state, so that the next time you start the nodeB/UE, it may crash with a UHD
  error. If this happens, simply start the nodeB/UE again.

- The UE may hang after ctrl-c in some cases, requiring you to kill it some
  other way. If this happens, use `ps aux` to identify the PID of of the
  nr-uesoftmodem process and do `kill -9 {PID}` to kill it.

"""

BIN_PATH = "/local/repository/bin"
ETC_PATH = "/local/repository/etc"
LOWLAT_IMG = "urn:publicid:IDN+emulab.net+image+PowderTeam:U18LL-SRSLTE"
UBUNTU_IMG = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
COMP_MANAGER_ID = "urn:publicid:IDN+emulab.net+authority+cm"
DEFAULT_NR_RAN_HASH = "1268b27c91be3a568dd352f2e9a21b3963c97432" # 2023.wk19
DEFAULT_NR_CN_HASH = "v1.5.0"
OAI_DEPLOY_SCRIPT = os.path.join(BIN_PATH, "deploy-oai.sh")

BENCH_SDR_IDS = {
    "bench_a": ["oai-wb-a1", "oai-wb-a2"],
    "bench_b": ["oai-wb-b1", "oai-wb-b2"],
    "bench_c": ["alex-3", "alex-4"],
}

pc = portal.Context()

node_types = [
    ("d430", "Emulab, d430"),
    ("d740", "Emulab, d740"),
]
pc.defineParameter(
    name="sdr_nodetype",
    description="Type of compute node paired with the SDRs",
    typ=portal.ParameterType.STRING,
    defaultValue=node_types[1],
    legalValues=node_types
)

pc.defineParameter(
    name="cn_nodetype",
    description="Type of compute node to use for CN node (if included)",
    typ=portal.ParameterType.STRING,
    defaultValue=node_types[0],
    legalValues=node_types
)

bench_ids = [
    ("bench_a", "Paired Radio Workbench A"),
    ("bench_b", "Paired Radio Workbench B"),
    ("bench_c", "Paired Radio Workbench C (Powder staff only)"),
]
pc.defineParameter(
    name="bench_id",
    description="Which workbench bench to use",
    typ=portal.ParameterType.STRING,
    defaultValue=bench_ids[0],
    legalValues=bench_ids
)

pc.defineParameter(
    name="oai_ran_commit_hash",
    description="Commit hash for OAI RAN",
    typ=portal.ParameterType.STRING,
    defaultValue="",
    advanced=True
)

pc.defineParameter(
    name="oai_cn_commit_hash",
    description="Commit hash for OAI (5G)CN",
    typ=portal.ParameterType.STRING,
    defaultValue="",
    advanced=True
)

pc.defineParameter(
    name="sdr_compute_image",
    description="Image to use for compute connected to SDRs",
    typ=portal.ParameterType.STRING,
    defaultValue="",
    advanced=True
)

params = pc.bindParameters()
request = pc.makeRequestRSpec()

role = "cn"
cn_node = request.RawPC("cn5g-docker-host")
cn_node.component_manager_id = COMP_MANAGER_ID
cn_node.hardware_type = params.cn_nodetype
cn_node.disk_image = UBUNTU_IMG
cn_if = cn_node.addInterface("cn-if")
cn_if.addAddress(rspec.IPv4Address("192.168.1.1", "255.255.255.0"))
cn_link = request.Link("cn-link")
cn_link.bandwidth = 10*1000*1000
cn_link.addInterface(cn_if)

if params.oai_cn_commit_hash:
    oai_cn_hash = params.oai_cn_commit_hash
else:
    oai_cn_hash = DEFAULT_NR_CN_HASH

cmd = '{} "{}" {}'.format(OAI_DEPLOY_SCRIPT, oai_cn_hash, role)
cn_node.addService(rspec.Execute(shell="bash", command=cmd))


if params.oai_ran_commit_hash:
    oai_ran_hash = params.oai_ran_commit_hash
else:
    oai_ran_hash = DEFAULT_NR_RAN_HASH

role = "nodeb"
nodeb = request.RawPC("gnb-comp")
nodeb.component_manager_id = COMP_MANAGER_ID
nodeb.hardware_type = params.sdr_nodetype
if params.sdr_compute_image:
    nodeb.disk_image = params.sdr_compute_image
else:
    nodeb.disk_image = UBUNTU_IMG

nodeb_cn_if = nodeb.addInterface("nodeb-cn-if")
nodeb_cn_if.addAddress(rspec.IPv4Address("192.168.1.2", "255.255.255.0"))
cn_link.addInterface(nodeb_cn_if)

nodeb_usrp_if = nodeb.addInterface("nodeb-usrp-if")
nodeb_usrp_if.addAddress(rspec.IPv4Address("192.168.40.1", "255.255.255.0"))

cmd = '{} "{}" {}'.format(OAI_DEPLOY_SCRIPT, oai_ran_hash, role)
nodeb.addService(rspec.Execute(shell="bash", command=cmd))
nodeb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-cpu.sh"))
nodeb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-sdr-iface.sh"))

nodeb_sdr = request.RawPC("gnb-sdr")
nodeb_sdr.component_manager_id = COMP_MANAGER_ID
nodeb_sdr.component_id = BENCH_SDR_IDS[params.bench_id][0]
nodeb_sdr_if = nodeb_sdr.addInterface("nodeb-sdr-if")

nodeb_sdr_link = request.Link("nodeb-sdr-link")
nodeb_sdr_link.bandwidth = 10*1000*1000
nodeb_sdr_link.addInterface(nodeb_usrp_if)
nodeb_sdr_link.addInterface(nodeb_sdr_if)

role = "ue"
ue1 = request.RawPC("nrue-comp-1")
ue1.component_manager_id = COMP_MANAGER_ID
ue1.hardware_type = params.sdr_nodetype
if params.sdr_compute_image:
    ue1.disk_image = params.sdr_compute_image
else:
    ue1.disk_image = UBUNTU_IMG

role = "ue"
ue2 = request.RawPC("nrue-comp-2")
ue2.component_manager_id = COMP_MANAGER_ID
ue2.hardware_type = params.sdr_nodetype
if params.sdr_compute_image:
    ue2.disk_image = params.sdr_compute_image
else:
    ue2.disk_image = UBUNTU_IMG

ue_usrp_if_1 = ue.addInterface("ue-usrp-if_1")
ue_usrp_if_1.addAddress(rspec.IPv4Address("192.168.40.1", "255.255.255.0"))
cmd = '{} "{}" {}'.format(OAI_DEPLOY_SCRIPT, oai_ran_hash, role)
ue1.addService(rspec.Execute(shell="bash", command=cmd))
ue1.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-cpu.sh"))
ue1.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-sdr-iface.sh"))

ue_usrp_if_2 = ue.addInterface("ue-usrp-if_2")
ue_usrp_if_2.addAddress(rspec.IPv4Address("192.168.40.1", "255.255.255.0"))
cmd = '{} "{}" {}'.format(OAI_DEPLOY_SCRIPT, oai_ran_hash, role)
ue2.addService(rspec.Execute(shell="bash", command=cmd))
ue2.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-cpu.sh"))
ue2.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-sdr-iface.sh"))

ue_sdr_1 = request.RawPC("nrue-sdr-1")
ue_sdr_1.component_manager_id = COMP_MANAGER_ID
ue_sdr_1.component_id = BENCH_SDR_IDS[params.bench_id][1]
ue_sdr_if_1 = ue_sdr_1.addInterface("ue-sdr-if_1")

ue_sdr_2 = request.RawPC("nrue-sdr-2")
ue_sdr_2.component_manager_id = COMP_MANAGER_ID
ue_sdr_2.component_id = BENCH_SDR_IDS[params.bench_id][1]
ue_sdr_if_2 = ue_sdr_2.addInterface("ue-sdr-if_2")

ue_sdr_link1 = request.Link("ue-sdr-link-1")
ue_sdr_link1.bandwidth = 10*1000*1000
ue_sdr_link1.addInterface(ue_usrp_if_1)
ue_sdr_link1.addInterface(ue_sdr_if_1)

ue_sdr_link2 = request.Link("ue-sdr-link-2")
ue_sdr_link2.bandwidth = 10*1000*1000
ue_sdr_link2.addInterface(ue_usrp_if_2)
ue_sdr_link2.addInterface(ue_sdr_if_2)

tour = IG.Tour()
tour.Description(IG.Tour.MARKDOWN, tourDescription)
tour.Instructions(IG.Tour.MARKDOWN, tourInstructions)
request.addTour(tour)

pc.printRequestRSpec(request)
