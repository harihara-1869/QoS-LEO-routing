// Original bounded compatibility harness. ns-3 owns all packet events.
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"
#include "ns3/traffic-control-module.h"
#include <vector>
namespace leo_probe {
using namespace ns3;
class Probe {
public:
  NodeContainer nodes;
  Ptr<PointToPointNetDevice> sourceDevice;
  Ptr<Ipv4StaticRouting> sourceRoutes;
  Ipv4Address gateway;
  uint32_t received = 0, dropped = 0, attempted = 0, sendFailures = 0;
  uint32_t packetCount = 0;
  double sendInterval = 0;
  Ptr<Socket> socket;
  Ipv4Address destination;
  void Send() {
    attempted++;
    if (socket->SendTo(Create<Packet>(1000), 0, InetSocketAddress(destination, 9000)) < 0) sendFailures++;
    if (attempted < packetCount) Simulator::Schedule(Seconds(sendInterval), &Probe::Send, this);
  }
  double firstRx = -1;
  void Receive(Ptr<const Packet>, const Address&) {
    received++;
    if (firstRx < 0) firstRx = Simulator::Now().GetSeconds();
  }
  void Drop(Ptr<const Packet>) { dropped++; }
  void Setup(const std::vector<double>& delays, uint32_t count, double interval) {
    nodes.Create(delays.size() + 1);
    InternetStackHelper stack;
    stack.Install(nodes);
    for (uint32_t i = 0; i < delays.size(); ++i) {
      PointToPointHelper link;
      link.DisableFlowControl();
      link.SetDeviceAttribute("DataRate", StringValue("1Mbps"));
      link.SetChannelAttribute("Delay", TimeValue(Seconds(delays[i])));
      link.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", QueueSizeValue(QueueSize("2p")));
      NetDeviceContainer devices = link.Install(nodes.Get(i), nodes.Get(i+1));
      Ipv4AddressHelper address;
      std::string subnet = "10.1." + std::to_string(i+1) + ".0";
      address.SetBase(subnet.c_str(), "255.255.255.0");
      auto interfaces = address.Assign(devices);
      destination = interfaces.GetAddress(1);
      if (i == 0) {
        gateway = interfaces.GetAddress(1);
        sourceDevice = DynamicCast<PointToPointNetDevice>(devices.Get(0));
        sourceDevice->GetQueue()->TraceConnectWithoutContext("Drop", MakeCallback(&Probe::Drop, this));
      }
    }
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    // Only source routing is under the Python controller's authority.
    sourceRoutes = CreateObject<Ipv4StaticRouting>();
    nodes.Get(0)->GetObject<Ipv4>()->SetRoutingProtocol(sourceRoutes);
    SetRouteEnabled(true);
    PacketSinkHelper sink("ns3::UdpSocketFactory", InetSocketAddress(Ipv4Address::GetAny(), 9000));
    auto receiver = sink.Install(nodes.Get(nodes.GetN()-1));
    receiver.Get(0)->TraceConnectWithoutContext("Rx", MakeCallback(&Probe::Receive, this));
    receiver.Start(Seconds(0));
    socket = Socket::CreateSocket(nodes.Get(0), UdpSocketFactory::GetTypeId());
    socket->Bind();
    packetCount = count;
    sendInterval = interval;
    Simulator::Schedule(Seconds(0.01), &Probe::Send, this);
  }
  void SetRouteEnabled(bool enabled) {
    while(sourceRoutes->GetNRoutes()) sourceRoutes->RemoveRoute(0);
    if(enabled) sourceRoutes->SetDefaultRoute(gateway, 1);
  }
  uint32_t QueuePackets() { return sourceDevice->GetQueue()->GetNPackets(); }
};
}
