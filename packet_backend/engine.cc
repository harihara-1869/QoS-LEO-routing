// LEO Phase 2 adapter. All packet events, queues and transports belong to ns-3.
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace leo {
using namespace ns3;

class PacketId : public Tag {
public:
  uint64_t value = 0;
  static TypeId GetTypeId() {
    static TypeId tid = TypeId("leo::PacketId").SetParent<Tag>().AddConstructor<PacketId>();
    return tid;
  }
  TypeId GetInstanceTypeId() const override { return GetTypeId(); }
  uint32_t GetSerializedSize() const override { return 8; }
  void Serialize(TagBuffer b) const override { b.WriteU64(value); }
  void Deserialize(TagBuffer b) override { value = b.ReadU64(); }
  void Print(std::ostream& out) const override { out << value; }
};

class TransmissionId : public PacketId {
public:
  static TypeId GetTypeId() {
    static TypeId tid = TypeId("leo::TransmissionId").SetParent<Tag>().AddConstructor<TransmissionId>();
    return tid;
  }
  TypeId GetInstanceTypeId() const override { return GetTypeId(); }
};

// Invalidates every transmission overlapping a down transition, even if the
// link returns before reception. Point-to-point serialization itself finishes.
class LinkError : public ErrorModel {
public:
  bool active = false;
  std::set<uint64_t> invalid;
  bool DoCorrupt(Ptr<Packet> p) override {
    TransmissionId token;
    bool stale = p->PeekPacketTag(token) && invalid.erase(token.value) != 0;
    return !active || stale;
  }
  void DoReset() override { invalid.clear(); }
};

// A stable source address lets TCP survive changes to its egress interface.
class IdentityRouting : public Ipv4StaticRouting {
public:
  Ipv4Address identity;
  Ptr<Ipv4Route> RouteOutput(Ptr<Packet> packet, const Ipv4Header& header,
                           Ptr<NetDevice> device, Socket::SocketErrno& error) override {
    auto route = Ipv4StaticRouting::RouteOutput(packet, header, device, error);
    if (route) route->SetSource(identity);
    return route;
  }
};

struct PacketRecord {
  uint32_t flow, size;
  double created, ended = -1;
  std::string status = "in_flight", reason = "horizon";
  std::vector<uint32_t> path;
};
struct Flow {
  uint32_t id, src, dst, size;
  std::string protocol;
  double start, end, rate;
  uint64_t maxBytes, accepted = 0, received = 0, txSegments = 0, retransmissions = 0;
  uint64_t attempted = 0;
  uint32_t highSequence = 0;
  Ptr<Socket> socket;
  bool connected = false;
};
struct Link {
  uint32_t a, b, queue;
  uint64_t rate;
  bool active = false;
  double delay = 0;
  Ptr<PointToPointNetDevice> dev[2];
  Ptr<LinkError> error[2]; // receiver-side error model
  uint32_t interface[2];
  Ipv4Address address[2];
  std::map<uint64_t, Ptr<const Packet>> flying[2]; // sender direction
};
struct Snapshot { double time; std::map<uint32_t, double> links; };

class Engine {
public:
  NodeContainer nodes;
  std::vector<Link> links;
  std::vector<Flow> flows;
  std::vector<Ptr<Socket>> receivers;
  std::vector<Snapshot> snapshots;
  std::vector<Ptr<Ipv4StaticRouting>> routes;
  std::vector<Ipv4Address> identities;
  std::map<uint64_t, PacketRecord> packets;
  std::map<std::pair<uint32_t,uint32_t>, uint32_t> nextHops;
  std::ofstream events, udp, tcp;
  double duration;
  uint64_t nextPacket = 0, nextTransmission = 0;
  uint32_t mtu, ttl;

  double Now() const { return Simulator::Now().GetSeconds(); }
  void Event(const std::string& kind, int64_t item, int64_t a, int64_t b,
             double value, const std::string& detail = "-") {
    events << Now() << '\t' << kind << '\t' << item << '\t' << a << '\t' << b
           << '\t' << value << '\t' << detail << '\n';
  }
  void Finish(Ptr<const Packet> p, const std::string& reason) {
    PacketId id;
    if (!p->PeekPacketTag(id)) return; // TCP is accounted by stream bytes and wire events
    auto& record = packets.at(id.value);
    if (record.status != "in_flight") return;
    record.status = "dropped"; record.reason = reason; record.ended = Now();
  }
  void QueueDrop(uint32_t link, uint32_t dir, Ptr<const Packet> p) {
    const std::string reason = links[link].active ? "queue_overflow" : "link_down_queued";
    Finish(p, reason);
    Event("drop", link, dir, p->GetUid(), p->GetSize(), reason);
  }
  void QueueSize(uint32_t link, uint32_t dir, uint32_t, uint32_t count) {
    Event("queue", link, dir, -1, count);
  }
  void TxBegin(uint32_t link, uint32_t dir, Ptr<const Packet> p) {
    TransmissionId token;
    // Metadata only: each hop/attempt needs a fresh identity, including retransmissions.
    ConstCast<Packet>(p)->RemovePacketTag(token);
    token.value = nextTransmission++;
    p->AddPacketTag(token);
    links[link].flying[dir][token.value] = p;
    Event("tx", link, dir, p->GetUid(), p->GetSize());
  }
  void RxEnd(uint32_t link, uint32_t receiver, Ptr<const Packet> p) {
    TransmissionId token;
    if (p->PeekPacketTag(token)) links[link].flying[1-receiver].erase(token.value);
  }
  void RxDrop(uint32_t link, uint32_t receiver, Ptr<const Packet> p) {
    TransmissionId token;
    if (p->PeekPacketTag(token)) links[link].flying[1-receiver].erase(token.value);
    Finish(p, "link_down_in_flight");
    Event("drop", link, 1-receiver, p->GetUid(), p->GetSize(), "link_down_in_flight");
  }
  void IpDrop(const Ipv4Header&, Ptr<const Packet> p, Ipv4L3Protocol::DropReason reason,
              Ptr<Ipv4> ip, uint32_t interface) {
    std::string name = reason == Ipv4L3Protocol::DROP_TTL_EXPIRED ? "ttl_expired" :
                       reason == Ipv4L3Protocol::DROP_INTERFACE_DOWN ? "interface_down" :
                       reason == Ipv4L3Protocol::DROP_NO_ROUTE || reason == Ipv4L3Protocol::DROP_ROUTE_ERROR ? "no_route" : "ip_drop";
    Finish(p, name);
    Event("ip_drop", ip->GetObject<Node>()->GetId(), interface, p->GetUid(), reason, name);
  }
  void Forward(uint32_t node, const Ipv4Header&, Ptr<const Packet> p, uint32_t) {
    PacketId id;
    if (p->PeekPacketTag(id)) packets.at(id.value).path.push_back(node);
  }
  void ReceiveUdp(uint32_t index, Ptr<Socket> socket) {
    while (auto p = socket->Recv()) {
      PacketId id;
      if (!p->PeekPacketTag(id)) throw std::runtime_error("UDP packet lost its identity tag");
      auto& record = packets.at(id.value);
      if (record.status != "in_flight") throw std::runtime_error("Invalidated UDP packet delivered");
      record.status = "delivered"; record.reason = "-"; record.ended = Now();
      record.path.push_back(flows[index].dst);
      flows[index].received += p->GetSize();
    }
  }
  void SendUdp(uint32_t index) {
    auto& f = flows[index];
    if (Now() >= f.end) return;
    const uint64_t id = nextPacket++;
    auto p = Create<Packet>(f.size);
    PacketId tag; tag.value = id; p->AddPacketTag(tag);
    packets.emplace(id, PacketRecord{f.id, f.size, Now(), -1, "in_flight", "horizon", {f.src}});
    f.attempted++;
    if (f.socket->SendTo(p, 0, InetSocketAddress(identities[f.dst], 9000+index)) < 0) Finish(p, "no_route");
    else f.accepted += f.size;
    // Integer sequence avoids cumulative floating point interval drift.
    double next = f.start + f.attempted * (f.size * 8.0 / f.rate);
    if (next < f.end && next < duration)
      Simulator::Schedule(Seconds(next) - Simulator::Now(), &Engine::SendUdp, this, index);
  }
  void ReceiveTcp(uint32_t index, Ptr<const Packet> p, const Address&) {
    flows[index].received += p->GetSize();
    Event("tcp_receive", flows[index].id, -1, -1, p->GetSize());
  }
  void TcpConnected(uint32_t index, Ptr<Socket>) { flows[index].connected = true; PumpTcp(index); }
  void TcpFailed(uint32_t index, Ptr<Socket>) { Event("tcp_connect_failed", flows[index].id, -1, -1, 0); }
  void TcpWritable(uint32_t index, Ptr<Socket>, uint32_t) { PumpTcp(index); }
  void PumpTcp(uint32_t index) {
    auto& f = flows[index];
    if (!f.connected || Now() >= f.end) return;
    while (f.accepted < f.maxBytes) {
      uint32_t size = std::min<uint64_t>(f.size, f.maxBytes-f.accepted);
      int sent = f.socket->Send(Create<Packet>(size));
      if (sent <= 0) break;
      f.accepted += sent;
    }
  }
  void StartTcp(uint32_t index) {
    auto& f = flows[index];
    f.socket->Connect(InetSocketAddress(identities[f.dst], 9000+index));
  }
  void Window(uint32_t index, uint32_t old, uint32_t value) {
    Event("cwnd", flows[index].id, old, -1, value);
  }
  void Threshold(uint32_t index, uint32_t old, uint32_t value) {
    Event("ssthresh", flows[index].id, old, -1, value);
  }
  void TcpTx(uint32_t index, Ptr<const Packet> p, const TcpHeader& header, Ptr<const TcpSocketBase>) {
    if (!p->GetSize()) return;
    auto& f = flows[index];
    uint32_t seq = header.GetSequenceNumber().GetValue();
    f.txSegments++;
    if (seq < f.highSequence) { f.retransmissions++; Event("tcp_retransmit", f.id, seq, -1, p->GetSize()); }
    f.highSequence = std::max(f.highSequence, seq+p->GetSize());
  }
  void Update(uint32_t index) {
    auto& snap = snapshots[index];
    for (uint32_t i=0; i<links.size(); ++i) {
      auto& l = links[i];
      bool up = snap.links.count(i);
      bool wasUp = l.active;
      if (l.active && !up) {
        l.active = false;
        for (uint32_t dir=0; dir<2; ++dir) {
          l.dev[dir]->GetQueue()->Flush();
          for (auto& [uid, p] : l.flying[dir]) {
            l.error[1-dir]->invalid.insert(uid);
            Finish(p, "link_down_in_flight");
          }
        }
      }
      if (wasUp != up || index == 0) Event("link", i, l.a, l.b, up);
      l.active = up;
      for (uint32_t dir=0; dir<2; ++dir) {
        l.error[dir]->active = up;
        auto ip = nodes.Get(dir ? l.b : l.a)->GetObject<Ipv4>();
        if (up) ip->SetUp(l.interface[dir]); else ip->SetDown(l.interface[dir]);
      }
      if (up) {
        l.delay = snap.links.at(i);
        l.dev[0]->GetChannel()->SetAttribute("Delay", TimeValue(Seconds(l.delay)));
      }
    }
    // Synchronous control handshake while ns-3 is paused inside this event.
    std::cout << "STATE " << std::setprecision(17) << Now() << ' ' << links.size()*2 << '\n';
    for (uint32_t i=0; i<links.size(); ++i)
      for (uint32_t d=0; d<2; ++d)
        std::cout << i << ' ' << d << ' ' << links[i].dev[d]->GetQueue()->GetNPackets()
                  << ' ' << links[i].dev[d]->GetQueue()->GetNBytes() << '\n';
    std::cout << "END\n" << std::flush;
    std::string word;
    uint32_t count;
    if (!(std::cin >> word >> count) || word != "ROUTES") throw std::runtime_error("Missing route response");
    for (auto route : routes) while(route->GetNRoutes()) route->RemoveRoute(0);
    std::map<std::pair<uint32_t,uint32_t>,uint32_t> updated;
    for (uint32_t i=0; i<count; ++i) {
      uint32_t src, dst, next;
      if (!(std::cin >> src >> dst >> next)) throw std::runtime_error("Truncated route response");
      if (src>=nodes.GetN() || dst>=nodes.GetN() || next>=nodes.GetN() || src==dst)
        throw std::runtime_error("Invalid routing endpoint");
      bool installed = false;
      for (auto& l : links) {
        if (!l.active) continue;
        int dir = l.a==src && l.b==next ? 0 : l.b==src && l.a==next ? 1 : -1;
        if (dir<0) continue;
        routes[src]->AddHostRouteTo(identities[dst], l.address[1-dir], l.interface[dir]);
        installed = true; break;
      }
      if (!installed) throw std::runtime_error("Route selects an unavailable link");
      if (!updated.emplace(std::make_pair(src,dst),next).second) throw std::runtime_error("Duplicate route");
    }
    for (auto& [key,next] : updated)
      if (!nextHops.count(key) || nextHops[key]!=next) Event("route", key.first, key.second, next, 1);
    for (auto& [key,next] : nextHops)
      if (!updated.count(key)) Event("route", key.first, key.second, -1, 0);
    nextHops = std::move(updated);
  }

  void Load(const std::string& input, const std::string& output) {
    std::ifstream in(input);
    uint32_t n, m, f, k, seed;
    std::string magic;
    in >> magic >> n >> m >> f >> k >> duration >> seed >> mtu >> ttl;
    if (magic!="LEO2" || !in) throw std::runtime_error("Invalid plan header");
    RngSeedManager::SetSeed(seed);
    Config::SetDefault("ns3::Ipv4L3Protocol::DefaultTtl", UintegerValue(ttl));
    Config::SetDefault("ns3::TcpL4Protocol::SocketType", TypeIdValue(TcpLinuxReno::GetTypeId()));
    Config::SetDefault("ns3::TcpSocketBase::Sack", BooleanValue(false));
    events.open(output+"/events.tsv"); udp.open(output+"/udp.tsv"); tcp.open(output+"/tcp.tsv");
    if (!events || !udp || !tcp) throw std::runtime_error("Cannot open result files");
    events << std::setprecision(17); udp << std::setprecision(17); tcp << std::setprecision(17);
    events << "time_s\tkind\titem\ta\tb\tvalue\tdetail\n";
    udp << "packet_id\tflow_id\tsize_bytes\tcreated_s\tstatus\tended_s\treason\tpath\n";
    tcp << "flow_id\taccepted_bytes\tdelivered_bytes\tdata_tx_segments\tretransmissions\n";
    nodes.Create(n);
    InternetStackHelper stack;
    Ipv4StaticRoutingHelper routing;
    stack.SetRoutingHelper(routing); stack.Install(nodes);
    for (uint32_t i=0; i<n; ++i) {
      auto ip = nodes.Get(i)->GetObject<Ipv4>();
      Ipv4Address identity(0xac100001 + i);
      identities.push_back(identity);
      ip->AddAddress(0, Ipv4InterfaceAddress(identity, Ipv4Mask("255.255.255.255")));
      auto stableRouting = CreateObject<IdentityRouting>();
      stableRouting->identity = identity;
      ip->SetRoutingProtocol(stableRouting);
      routes.push_back(stableRouting);
      auto l3 = nodes.Get(i)->GetObject<Ipv4L3Protocol>();
      l3->TraceConnectWithoutContext("Drop", MakeCallback(&Engine::IpDrop, this));
      l3->TraceConnectWithoutContext("UnicastForward", MakeCallback(&Engine::Forward, this).Bind(i));
    }
    links.resize(m);
    for (uint32_t i=0; i<m; ++i) {
      auto& l = links[i]; in >> l.a >> l.b >> l.rate >> l.queue;
      PointToPointHelper helper; helper.DisableFlowControl();
      helper.SetDeviceAttribute("DataRate", DataRateValue(DataRate(l.rate)));
      helper.SetDeviceAttribute("Mtu", UintegerValue(mtu));
      helper.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", QueueSizeValue(ns3::QueueSize(std::to_string(l.queue)+"p")));
      auto devices = helper.Install(nodes.Get(l.a), nodes.Get(l.b));
      Ipv4AddressHelper address;
      address.SetBase(Ipv4Address(0x0a000000+i*4), Ipv4Mask("255.255.255.252"));
      auto interfaces = address.Assign(devices);
      for (uint32_t d=0; d<2; ++d) {
        l.dev[d] = DynamicCast<PointToPointNetDevice>(devices.Get(d));
        l.interface[d] = nodes.Get(d?l.b:l.a)->GetObject<Ipv4>()->GetInterfaceForDevice(l.dev[d]);
        l.address[d] = interfaces.GetAddress(d);
        l.error[d] = CreateObject<LinkError>(); l.dev[d]->SetReceiveErrorModel(l.error[d]);
        l.dev[d]->GetQueue()->TraceConnectWithoutContext("Drop", MakeCallback(&Engine::QueueDrop,this).Bind(i,d));
        l.dev[d]->GetQueue()->TraceConnectWithoutContext("PacketsInQueue", MakeCallback(&Engine::QueueSize,this).Bind(i,d));
        l.dev[d]->TraceConnectWithoutContext("PhyTxBegin", MakeCallback(&Engine::TxBegin,this).Bind(i,d));
        l.dev[d]->TraceConnectWithoutContext("PhyRxEnd", MakeCallback(&Engine::RxEnd,this).Bind(i,d));
        l.dev[d]->TraceConnectWithoutContext("PhyRxDrop", MakeCallback(&Engine::RxDrop,this).Bind(i,d));
      }
    }
    flows.resize(f);
    for (auto& flow : flows)
      in >> flow.id >> flow.src >> flow.dst >> flow.protocol >> flow.start >> flow.end >> flow.rate >> flow.size >> flow.maxBytes;
    snapshots.resize(k);
    for (auto& snap : snapshots) {
      uint32_t count; in >> snap.time >> count;
      for (uint32_t i=0; i<count; ++i) { uint32_t link; double delay; in >> link >> delay; snap.links[link]=delay; }
    }
    if (!in) throw std::runtime_error("Truncated scenario plan");
    // All topology/control events are registered before traffic events.
    for (uint32_t i=0; i<k; ++i) Simulator::Schedule(Seconds(snapshots[i].time), &Engine::Update, this, i);
    for (uint32_t i=0; i<f; ++i) {
      auto& flow = flows[i];
      if (flow.protocol=="udp") {
        auto receiver = Socket::CreateSocket(nodes.Get(flow.dst), UdpSocketFactory::GetTypeId());
        receiver->Bind(InetSocketAddress(identities[flow.dst],9000+i));
        receivers.push_back(receiver);
        receiver->SetRecvCallback(MakeCallback(&Engine::ReceiveUdp,this).Bind(i));
        flow.socket = Socket::CreateSocket(nodes.Get(flow.src), UdpSocketFactory::GetTypeId());
        flow.socket->Bind(InetSocketAddress(identities[flow.src],0));
        if (flow.rate>0) Simulator::Schedule(Seconds(flow.start), &Engine::SendUdp,this,i);
      } else {
        PacketSinkHelper sink("ns3::TcpSocketFactory",InetSocketAddress(identities[flow.dst],9000+i));
        auto apps = sink.Install(nodes.Get(flow.dst)); apps.Start(Seconds(0));
        apps.Get(0)->TraceConnectWithoutContext("Rx",MakeCallback(&Engine::ReceiveTcp,this).Bind(i));
        flow.socket = Socket::CreateSocket(nodes.Get(flow.src),TcpSocketFactory::GetTypeId());
        flow.socket->SetAttribute("SegmentSize",UintegerValue(flow.size));
        flow.socket->Bind(InetSocketAddress(identities[flow.src],0));
        flow.socket->SetConnectCallback(MakeCallback(&Engine::TcpConnected,this).Bind(i),MakeCallback(&Engine::TcpFailed,this).Bind(i));
        flow.socket->SetSendCallback(MakeCallback(&Engine::TcpWritable,this).Bind(i));
        flow.socket->TraceConnectWithoutContext("CongestionWindow",MakeCallback(&Engine::Window,this).Bind(i));
        flow.socket->TraceConnectWithoutContext("SlowStartThreshold",MakeCallback(&Engine::Threshold,this).Bind(i));
        flow.socket->TraceConnectWithoutContext("Tx",MakeCallback(&Engine::TcpTx,this).Bind(i));
        Simulator::Schedule(Seconds(flow.start),&Engine::StartTcp,this,i);
      }
    }
  }
  void Run() {
    Simulator::Stop(Seconds(duration)); Simulator::Run();
    for (auto& [id,r] : packets) {
      udp << id << '\t' << r.flow << '\t' << r.size << '\t' << r.created << '\t' << r.status << '\t'
          << (r.ended<0?duration:r.ended) << '\t' << r.reason << '\t';
      for (size_t i=0;i<r.path.size();++i) { if(i) udp << ','; udp << r.path[i]; }
      udp << '\n';
    }
    for (auto& f : flows) if(f.protocol=="tcp")
      tcp << f.id << '\t' << f.accepted << '\t' << f.received << '\t' << f.txSegments << '\t' << f.retransmissions << '\n';
    Simulator::Destroy(); std::cout << "DONE\n" << std::flush;
  }
};

void CheckReno() {
  auto reno = CreateObject<TcpLinuxReno>(); auto state = CreateObject<TcpSocketState>();
  state->m_segmentSize=1000; state->m_cWnd=10000; state->m_ssThresh=20000;
  reno->IncreaseWindow(state,1); uint32_t slow=state->m_cWnd;
  state->m_cWnd=10000;
  uint32_t half=reno->GetSsThresh(state,10000);
  state->m_cWnd=20000; state->m_ssThresh=10000; state->m_isCwndLimited=true;
  for(int i=0;i<20;++i) reno->IncreaseWindow(state,1);
  std::cout << slow << ' ' << half << ' ' << state->m_cWnd << '\n';
  if(slow!=11000 || half!=5000 || state->m_cWnd!=21000) throw std::runtime_error("Reno arithmetic check failed");
}
}
int main(int argc,char** argv) {
  try {
    if(argc==2 && std::string(argv[1])=="--check-reno") { leo::CheckReno(); return 0; }
    if(argc!=3) throw std::runtime_error("Usage: engine PLAN OUTPUT_DIRECTORY");
    leo::Engine engine; engine.Load(argv[1],argv[2]); engine.Run(); return 0;
  } catch(const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
