#pragma once
// Optional atomic telemetry, separate from numerical outputs and stdout.
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <string>
#include <unistd.h>

class LiveProgress {
    std::string path_, run_, phase_;
    unsigned long long seq_=0;
    std::chrono::steady_clock::time_point last_{};
public:
    LiveProgress() {
        const char* path=std::getenv("PLATFORM_ALGORITHM_PROGRESS_PATH");
        const char* run=std::getenv("PLATFORM_PROGRESS_RUN_ID");
        if(path && run){path_=path;run_=run;}
        if(const char* seq=std::getenv("PLATFORM_PROGRESS_SEQ"))seq_=std::stoull(seq);
    }
    void emit(const std::string& phase,size_t current,size_t total,const std::string& unit,bool force=false) {
        if(path_.empty())return;
        auto now=std::chrono::steady_clock::now();
        if(!force && phase==phase_ && now-last_<std::chrono::milliseconds(500))return;
        std::string tmp=path_+".tmp-"+std::to_string(getpid());
        auto epoch=std::time(nullptr);
        std::ofstream out(tmp);
        out<<"{\"protocol\":1,\"run_id\":\""<<run_<<"\",\"seq\":"<<++seq_
           <<",\"phase\":\""<<phase<<"\",\"current\":"<<current<<",\"total\":"<<total
           <<",\"progress_scope\":\""<<(total?"step":"none")<<"\",\"unit\":\""<<unit
           <<"\",\"counter_updated_at\":\""<<std::put_time(std::gmtime(&epoch),"%Y-%m-%dT%H:%M:%SZ")<<"\"}";
        out.close();if(!out)throw std::runtime_error("Progress snapshot write failed");
        std::filesystem::rename(tmp,path_);phase_=phase;last_=now;
    }
};
