#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(not(windows))]
fn main() {
    eprintln!("Booru Studio Supervisor is Windows-only");
    std::process::exit(2);
}

#[cfg(windows)]
mod win {
    use std::ffi::{c_void, OsStr};
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::{null, null_mut};
    use std::time::Duration;

    type Handle = *mut c_void;
    type Bool = i32;
    type Dword = u32;
    const FALSE: Bool = 0;
    const CREATE_SUSPENDED: Dword = 0x0000_0004;
    const CREATE_UNICODE_ENVIRONMENT: Dword = 0x0000_0400;
    const EXTENDED_STARTUPINFO_PRESENT: Dword = 0x0008_0000;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: usize = 0x0000_2000;
    const PROC_THREAD_ATTRIBUTE_HANDLE_LIST: usize = 0x0002_0002;
    const WAIT_OBJECT_0: Dword = 0;
    const WAIT_TIMEOUT: Dword = 258;
    const GENERIC_READ: Dword = 0x8000_0000;
    const GENERIC_WRITE: Dword = 0x4000_0000;
    const OPEN_EXISTING: Dword = 3;
    const INVALID_HANDLE_VALUE: Handle = -1isize as Handle;

    #[repr(C)] struct SecurityAttributes { n_length: Dword, security_descriptor: *mut c_void, inherit_handle: Bool }
    #[repr(C)] struct StartupInfoW { cb: Dword, reserved: *mut u16, desktop: *mut u16, title: *mut u16, x:Dword,y:Dword,x_size:Dword,y_size:Dword,x_count_chars:Dword,y_count_chars:Dword,fill_attribute:Dword,flags:Dword,show_window:u16,cb_reserved2:u16,reserved2:*mut u8,std_input:Handle,std_output:Handle,std_error:Handle }
    #[repr(C)] struct StartupInfoExW { startup: StartupInfoW, attribute_list: *mut c_void }
    #[repr(C)] struct ProcessInformation { process:Handle, thread:Handle, process_id:Dword, thread_id:Dword }
    #[repr(C)] struct IoCounters { read_operation_count:u64,write_operation_count:u64,other_operation_count:u64,read_transfer_count:u64,write_transfer_count:u64,other_transfer_count:u64 }
    #[repr(C)] struct BasicLimit { per_process_user_time_limit:i64,per_job_user_time_limit:i64,limit_flags:Dword,minimum_working_set_size:usize,maximum_working_set_size:usize,active_process_limit:Dword,affinity:usize,priority_class:Dword,scheduling_class:Dword }
    #[repr(C)] struct ExtendedLimit { basic:BasicLimit, io:IoCounters, process_memory_limit:usize, job_memory_limit:usize, peak_process_memory_used:usize, peak_job_memory_used:usize }

    #[link(name="kernel32")]
    unsafe extern "system" {
        fn CreateJobObjectW(attrs:*const c_void, name:*const u16) -> Handle;
        fn SetInformationJobObject(job:Handle, class:i32, info:*const c_void, len:Dword) -> Bool;
        fn AssignProcessToJobObject(job:Handle, process:Handle) -> Bool;
        fn CreatePipe(read:*mut Handle, write:*mut Handle, attrs:*mut SecurityAttributes, size:Dword) -> Bool;
        fn WaitNamedPipeW(name:*const u16, timeout:Dword) -> Bool;
        fn CreateFileW(name:*const u16, access:Dword, share:Dword, attrs:*const c_void, creation:Dword, flags:Dword, template:Handle) -> Handle;
        fn WriteFile(handle:Handle, buffer:*const c_void, bytes:Dword, written:*mut Dword, ov:*mut c_void) -> Bool;
        fn SetHandleInformation(handle:Handle, mask:Dword, flags:Dword) -> Bool;
        fn InitializeProcThreadAttributeList(list:*mut c_void, count:Dword, flags:Dword, size:*mut usize) -> Bool;
        fn UpdateProcThreadAttribute(list:*mut c_void, flags:Dword, attribute:usize, value:*const c_void, size:usize, prev:*mut c_void, ret:*mut usize) -> Bool;
        fn DeleteProcThreadAttributeList(list:*mut c_void);
        fn CreateProcessW(app:*const u16, command:*mut u16, pa:*const c_void, ta:*const c_void, inherit:Bool, flags:Dword, env:*const c_void, cwd:*const u16, startup:*mut StartupInfoW, pi:*mut ProcessInformation) -> Bool;
        fn ResumeThread(thread:Handle) -> Dword;
        fn WaitForSingleObject(handle:Handle, millis:Dword) -> Dword;
        fn GetExitCodeProcess(process:Handle, code:*mut Dword) -> Bool;
        fn ReadFile(handle:Handle, buffer:*mut c_void, bytes:Dword, read:*mut Dword, ov:*mut c_void) -> Bool;
        fn PeekNamedPipe(handle:Handle, buffer:*mut c_void, size:Dword, read:*mut Dword, avail:*mut Dword, left:*mut Dword) -> Bool;
        fn QueryUnbiasedInterruptTime(value:*mut u64) -> Bool;
        fn CloseHandle(handle:Handle) -> Bool;
        fn TerminateJobObject(job:Handle, code:u32) -> Bool;
        fn GetCurrentProcessId() -> Dword;
    }

    fn wide(value:&OsStr) -> Vec<u16> { value.encode_wide().chain(Some(0)).collect() }
    fn awake_ms() -> u64 { let mut v=0u64; unsafe { if QueryUnbiasedInterruptTime(&mut v)==0 { return 0; } } v/10_000 }

    // Quote one argv element using the CommandLineToArgvW-compatible escaping rules.
    // Backslashes before a literal quote are doubled plus one; trailing backslashes are
    // doubled before the closing quote. This preserves spaces, Unicode paths and paths
    // ending in a backslash without teaching the Supervisor anything about Core arguments.
    fn quote_windows_arg(value: &OsStr) -> String {
        let text=value.to_string_lossy();
        if text.is_empty() { return "\"\"".to_string(); }
        if !text.chars().any(|ch| ch==' ' || ch=='\t' || ch=='\"') { return text.into_owned(); }
        let mut out=String::from("\"");
        let mut slashes=0usize;
        for ch in text.chars() {
            if ch=='\\' { slashes+=1; continue; }
            if ch=='\"' {
                out.push_str(&"\\".repeat(slashes*2+1));
                out.push('\"');
            } else {
                out.push_str(&"\\".repeat(slashes));
                out.push(ch);
            }
            slashes=0;
        }
        out.push_str(&"\\".repeat(slashes*2));
        out.push('\"');
        out
    }

    // Never issue a synchronous ReadFile until the complete requested byte count is already
    // buffered. The bounded poll means an accepted-but-hung Core cannot hang the Supervisor.
    fn wait_pipe_bytes(handle: Handle, needed: u32) -> bool {
        for _ in 0..75 { // <= ~1.5 s of active polling; sleep/resume cannot make this infinite.
            let mut avail=0u32;
            if unsafe{PeekNamedPipe(handle,null_mut(),0,null_mut(),&mut avail,null_mut())}==0 { return false; }
            if avail>=needed { return true; }
            std::thread::sleep(Duration::from_millis(20));
        }
        false
    }

    fn qlocal_health(endpoint: &str) -> bool {
        let pipe=wide(OsStr::new(&format!(r"\\.\pipe\{}",endpoint)));
        unsafe { if WaitNamedPipeW(pipe.as_ptr(),1500)==0 { return false; } }
        let h=unsafe{CreateFileW(pipe.as_ptr(),GENERIC_READ|GENERIC_WRITE,0,null(),OPEN_EXISTING,0,null_mut())};
        if h==INVALID_HANDLE_VALUE { return false; }
        let body=br#"{"family":"ui-core","version":{"major":1,"minor":0},"plane":"CONTROL","message_type":"HEALTH_CHECK","message_id":"supervisor-health","trace_id":null,"payload":{}}"#;
        let len=(body.len() as u32).to_be_bytes();
        let mut frame=Vec::with_capacity(4+body.len()); frame.extend_from_slice(&len); frame.extend_from_slice(body);
        let mut written=0u32; let ok=unsafe{WriteFile(h,frame.as_ptr() as *const c_void,frame.len() as u32,&mut written,null_mut())};
        if ok==0 || written!=frame.len() as u32 { unsafe{CloseHandle(h);} return false; }
        if !wait_pipe_bytes(h,4) { unsafe{CloseHandle(h);} return false; }
        let mut head=[0u8;4]; let mut got=0u32;
        if unsafe{ReadFile(h,head.as_mut_ptr() as *mut c_void,4,&mut got,null_mut())}==0 || got!=4 { unsafe{CloseHandle(h);} return false; }
        let n=u32::from_be_bytes(head) as usize; if n==0 || n>64*1024 { unsafe{CloseHandle(h);} return false; }
        if !wait_pipe_bytes(h,n as u32) { unsafe{CloseHandle(h);} return false; }
        let mut reply=vec![0u8;n]; let mut got_body=0u32;
        if unsafe{ReadFile(h,reply.as_mut_ptr() as *mut c_void,n as u32,&mut got_body,null_mut())}==0 || got_body!=n as u32 { unsafe{CloseHandle(h);} return false; }
        unsafe{CloseHandle(h);}
        std::str::from_utf8(&reply).map(|v| v.contains("\"message_type\":\"HEALTH_RESPONSE\"") && v.contains("\"status\":\"READY\"")).unwrap_or(false)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn windows_argv_quoting_preserves_common_runtime_paths() {
            assert_eq!(quote_windows_arg(OsStr::new("plain")), "plain");
            assert_eq!(quote_windows_arg(OsStr::new("")), "\"\"");
            assert_eq!(quote_windows_arg(OsStr::new(r"C:\Program Files\Booru Studio\")), r#""C:\Program Files\Booru Studio\\""#);
            assert_eq!(quote_windows_arg(OsStr::new("alpha\"beta")), "\"alpha\\\"beta\"");
        }
    }

    pub fn run() -> i32 {
        let args:Vec<_>=std::env::args_os().collect();
        if args.len()<4 || args[2] != "--endpoint" { return 64; }
        // The stable Launcher creates this value once and gives it to both the UI and this
        // Supervisor. Generating it here would make the UI/Core endpoint handoff racy.
        let core=wide(&args[1]);
        let endpoint=args[3].to_string_lossy().into_owned();
        if !endpoint.starts_with("booru-v10-core-") || endpoint.len()>240 { return 64; }
        let mut read:Handle=null_mut(); let mut write:Handle=null_mut();
        let mut sa=SecurityAttributes{n_length:std::mem::size_of::<SecurityAttributes>() as u32,security_descriptor:null_mut(),inherit_handle:1};
        unsafe { if CreatePipe(&mut read,&mut write,&mut sa,0)==0 { return 70; } }
        // Supervisor read side must never leak to Core; write side is the only inherited HANDLE.
        unsafe { SetHandleInformation(read,1,0); }
        let job=unsafe{CreateJobObjectW(null(),null())}; if job.is_null(){return 71;}
        let mut limits:ExtendedLimit=unsafe{std::mem::zeroed()}; limits.basic.limit_flags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE as u32;
        unsafe { if SetInformationJobObject(job,JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,&limits as *const _ as *const c_void,std::mem::size_of::<ExtendedLimit>() as u32)==0{return 72;} }

        let mut bytes=0usize; unsafe{InitializeProcThreadAttributeList(null_mut(),1,0,&mut bytes);}
        let mut storage=vec![0u8;bytes]; let list=storage.as_mut_ptr() as *mut c_void;
        unsafe { if InitializeProcThreadAttributeList(list,1,0,&mut bytes)==0{return 73;} }
        let handles=[write];
        unsafe { if UpdateProcThreadAttribute(list,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles.as_ptr() as *const c_void,std::mem::size_of_val(&handles),null_mut(),null_mut())==0{return 74;} }
        let mut si:StartupInfoExW=unsafe{std::mem::zeroed()}; si.startup.cb=std::mem::size_of::<StartupInfoExW>() as u32; si.attribute_list=list;
        let opaque=args.iter().skip(4).map(|v| format!(" {}",quote_windows_arg(v))).collect::<String>();
        let cmd=format!("{} --endpoint {} --supervisor-heartbeat-handle {}{}",quote_windows_arg(&args[1]),endpoint,write as usize,opaque);
        let mut command=wide(OsStr::new(&cmd)); let mut pi:ProcessInformation=unsafe{std::mem::zeroed()};
        let ok=unsafe{CreateProcessW(core.as_ptr(),command.as_mut_ptr(),null(),null(),1,CREATE_SUSPENDED|CREATE_UNICODE_ENVIRONMENT|EXTENDED_STARTUPINFO_PRESENT,null(),null(),&mut si.startup,&mut pi)};
        unsafe{DeleteProcThreadAttributeList(list); CloseHandle(write);}
        if ok==0{return 75;}
        // Assign before ResumeThread closes the child-escape race.
        if unsafe{AssignProcessToJobObject(job,pi.process)}==0 { unsafe{CloseHandle(pi.thread);CloseHandle(pi.process);} return 76; }
        unsafe{ResumeThread(pi.thread);CloseHandle(pi.thread);}

        let mut last_hb=awake_ms(); let mut buf=[0u8;256];
        loop {
            let wait=unsafe{WaitForSingleObject(pi.process,500)};
            if wait==WAIT_OBJECT_0 { let mut code=0; unsafe{GetExitCodeProcess(pi.process,&mut code);CloseHandle(pi.process);CloseHandle(read);CloseHandle(job);} return code as i32; }
            if wait!=WAIT_TIMEOUT { unsafe{TerminateJobObject(job,0xE001);CloseHandle(pi.process);CloseHandle(read);CloseHandle(job);} return 77; }
            let mut avail=0u32; unsafe{PeekNamedPipe(read,null_mut(),0,null_mut(),&mut avail,null_mut());}
            if avail>0 { let mut got=0u32; unsafe{ReadFile(read,buf.as_mut_ptr() as *mut c_void,avail.min(buf.len() as u32),&mut got,null_mut());} if got>0 {last_hb=awake_ms();} }
            let age=awake_ms().saturating_sub(last_hb);
            // One missed heartbeat never kills. After suspect threshold, actively probe the Qt
            // event loop through QLocal. Only process-alive + heartbeat timeout + failed probe
            // across the bounded grace reaches forced Job Object termination.
            if age>8_000 && qlocal_health(&endpoint) { last_hb=awake_ms(); }
            else if age>20_000 { unsafe{TerminateJobObject(job,0xE002);CloseHandle(pi.process);CloseHandle(read);CloseHandle(job);} return 78; }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

#[cfg(windows)]
fn main() { std::process::exit(win::run()); }
