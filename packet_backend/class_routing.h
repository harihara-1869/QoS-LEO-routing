#pragma once
#include "ns3/internet-module.h"
#include "qos_queue.h"

namespace leo {
// Preserve stable TCP source identities and dispatch each packet to its class table.
class IdentityRouting : public ns3::Ipv4StaticRouting {
public:
  ns3::Ipv4Address identity;
  bool perClass = false;
  std::array<ns3::Ptr<ns3::Ipv4StaticRouting>, 3> classes;
  void SetIpv4(ns3::Ptr<ns3::Ipv4> ip) override {
    ns3::Ipv4StaticRouting::SetIpv4(ip);
    if (perClass) for (auto& table : classes) {
      table = ns3::CreateObject<ns3::Ipv4StaticRouting>();
      table->SetIpv4(ip);
    }
  }
  void NotifyInterfaceUp(uint32_t i) override {
    ns3::Ipv4StaticRouting::NotifyInterfaceUp(i);
    for (auto table : classes) if (table) table->NotifyInterfaceUp(i);
  }
  void NotifyInterfaceDown(uint32_t i) override {
    ns3::Ipv4StaticRouting::NotifyInterfaceDown(i);
    for (auto table : classes) if (table) table->NotifyInterfaceDown(i);
  }
  void NotifyAddAddress(uint32_t i, ns3::Ipv4InterfaceAddress a) override {
    ns3::Ipv4StaticRouting::NotifyAddAddress(i, a);
    for (auto table : classes) if (table) table->NotifyAddAddress(i, a);
  }
  void NotifyRemoveAddress(uint32_t i, ns3::Ipv4InterfaceAddress a) override {
    ns3::Ipv4StaticRouting::NotifyRemoveAddress(i, a);
    for (auto table : classes) if (table) table->NotifyRemoveAddress(i, a);
  }
  ns3::Ptr<ns3::Ipv4Route> RouteOutput(ns3::Ptr<ns3::Packet> p, const ns3::Ipv4Header& h,
      ns3::Ptr<ns3::NetDevice> device, ns3::Socket::SocketErrno& error) override {
    auto route = perClass ? classes[p ? ClassOf(p) : 2]->RouteOutput(p, h, device, error)
                         : ns3::Ipv4StaticRouting::RouteOutput(p, h, device, error);
    if (route) route->SetSource(identity);
    return route;
  }
  bool RouteInput(ns3::Ptr<const ns3::Packet> p, const ns3::Ipv4Header& h,
      ns3::Ptr<const ns3::NetDevice> device, const UnicastForwardCallback& ucb,
      const MulticastForwardCallback& mcb, const LocalDeliverCallback& lcb,
      const ErrorCallback& ecb) override {
    return perClass ? classes[ClassOf(p)]->RouteInput(p, h, device, ucb, mcb, lcb, ecb)
                    : ns3::Ipv4StaticRouting::RouteInput(p, h, device, ucb, mcb, lcb, ecb);
  }
protected:
  void DoDispose() override {
    for (auto& table : classes) { if (table) table->Dispose(); table = nullptr; }
    ns3::Ipv4StaticRouting::DoDispose();
  }
};
}
