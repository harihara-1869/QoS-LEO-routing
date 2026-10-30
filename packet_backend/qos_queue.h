#pragma once
#include "ns3/network-module.h"
#include <array>
#include <deque>
#include <functional>

namespace leo {
using namespace ns3;

class ServiceClass : public Tag {
public:
  uint8_t value = 2; // CONTROL=0, REALTIME=1, BULK=2
  static TypeId GetTypeId() {
    static TypeId tid = TypeId("leo::ServiceClass").SetParent<Tag>().AddConstructor<ServiceClass>();
    return tid;
  }
  TypeId GetInstanceTypeId() const override { return GetTypeId(); }
  uint32_t GetSerializedSize() const override { return 1; }
  void Serialize(TagBuffer b) const override { b.WriteU8(value); }
  void Deserialize(TagBuffer b) override { value = b.ReadU8(); }
  void Print(std::ostream& out) const override { out << unsigned(value); }
};
inline uint32_t ClassOf(Ptr<const Packet> packet) {
  ServiceClass tag;
  return packet->PeekPacketTag(tag) ? tag.value : 2; // TCP bulk, including ACKs
}

// Work-conserving byte deficit round robin; separate admission reservations
// prevent a flood in one class from taking all another class's queue slots.
class ClassQueue : public Queue<Packet> {
public:
  static TypeId GetTypeId() {
    static TypeId tid = TypeId("leo::ClassQueue").SetParent<Queue<Packet>>().AddConstructor<ClassQueue>();
    return tid;
  }
  std::function<void(uint32_t, uint32_t)> changed;
  std::array<uint64_t,3> arrived{0,0,0}, served{0,0,0}, rejected{0,0,0};
  void Configure(uint32_t total, const std::array<uint32_t,3>& weights, uint32_t baseQuantum) {
    SetMaxSize(QueueSize(std::to_string(total)+"p"));
    limit = {total/3,total/3,total-2*(total/3)};
    for (uint32_t c=0;c<3;++c) quantum[c] = uint64_t(baseQuantum)*weights[c];
  }
  uint32_t ClassPackets(uint32_t c) const { return heads[c].size(); }
  uint32_t ClassBytes(uint32_t c) const { return bytes[c]; }
  bool Enqueue(Ptr<Packet> packet) override {
    uint32_t c = ClassOf(packet);
    if (c>=3) { DropBeforeEnqueue(packet); return false; }
    arrived[c]+=packet->GetSize();
    if (heads[c].size()>=limit[c]) { rejected[c]+=packet->GetSize(); DropBeforeEnqueue(packet); return false; }
    Iterator inserted;
    if (!DoEnqueue(GetContainer().end(),packet,inserted)) return false;
    heads[c].push_back(inserted); bytes[c]+=packet->GetSize();
    Notify(c);
    return true;
  }
  Ptr<Packet> Dequeue() override { return Take(false); }
  Ptr<Packet> Remove() override { return Take(true); }
  Ptr<const Packet> Peek() const override {
    auto d = deficit; auto c = cursor; bool visit = newVisit;
    int selected = Select(d,c,visit);
    return selected<0 ? nullptr : DoPeek(heads[selected].front());
  }
private:
  std::array<std::deque<ConstIterator>,3> heads;
  std::array<uint32_t,3> limit{1,1,1}, bytes{0,0,0};
  std::array<uint64_t,3> deficit{0,0,0}, quantum{6000,3000,1500};
  uint32_t cursor=0;
  bool newVisit=true;
  void Notify(uint32_t c) { if(changed) changed(c,heads[c].size()); }
  int Select(std::array<uint64_t,3>& d, uint32_t& c, bool& visit) const {
    if (IsEmpty()) return -1;
    for (;;) {
      if (heads[c].empty()) d[c]=0;
      else {
        if (visit) d[c]+=quantum[c];
        visit=false;
        if ((*heads[c].front())->GetSize()<=d[c]) {
          d[c]-=(*heads[c].front())->GetSize();
          return c;
        }
      }
      c=(c+1)%3; visit=true;
    }
  }
  Ptr<Packet> Take(bool drop) {
    int c=Select(deficit,cursor,newVisit);
    if(c<0) return nullptr;
    auto position=heads[c].front(); heads[c].pop_front();
    bytes[c]-=(*position)->GetSize();
    if(!drop) served[c]+=(*position)->GetSize();
    auto packet=drop ? DoRemove(position) : DoDequeue(position);
    Notify(c);
    if(heads[c].empty()) { deficit[c]=0; cursor=(c+1)%3; newVisit=true; }
    if(IsEmpty()) { deficit={0,0,0}; cursor=0; newVisit=true; }
    return packet;
  }
};
}
