"""Optional, bounded source analysis using the OpenAI Responses API.

Source text stays in request memory and is never written to logs or persisted by
this module. The model can request a small number of literal source lookups.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
import certifi

ATTR_SCHEMA={"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}}
SCHEMA = {
    "type":"object","additionalProperties":False,
    "properties":{
        "entities":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"id":{"type":"string"},"kind":{"type":"string"},"name":{"type":"string"},"expression":{"type":["string","null"]},"attributes":ATTR_SCHEMA,"evidence":{"type":"object","properties":{"file":{"type":"string"},"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["file","start_line","end_line"],"additionalProperties":False}},"required":["id","kind","name","expression","attributes","evidence"]}},
        "relationships":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"source":{"type":"string"},"target":{"type":"string"},"kind":{"type":"string"},"attributes":ATTR_SCHEMA,"evidence":{"type":"object","properties":{"file":{"type":"string"},"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["file","start_line","end_line"],"additionalProperties":False}},"required":["source","target","kind","attributes","evidence"]}},
        "symbols":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"expression":{"type":"string"},"default_value":{"type":["string","null"]},"evidence":{"type":"object","properties":{"file":{"type":"string"},"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["file","start_line","end_line"],"additionalProperties":False}},"required":["name","expression","default_value","evidence"]}},
        "warnings":{"type":"array","items":{"type":"string"}}
    },"required":["entities","relationships","symbols","warnings"]
}


def _response(payload: dict) -> dict:
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise RuntimeError("Agent analysis requested but OPENAI_API_KEY is not configured")
    base=os.environ.get("OPENAI_BASE_URL","https://api.openai.com/v1").rstrip("/")
    request=urllib.request.Request(f"{base}/responses",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
    timeout=float(os.environ.get("GRAPHIFIER_AGENT_TIMEOUT","35"))
    cafile=os.environ.get("SSL_CERT_FILE") or certifi.where()
    try:
        with urllib.request.urlopen(request,timeout=timeout,context=ssl.create_default_context(cafile=cafile)) as response: return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI Responses API returned HTTP {exc.code}") from exc
    except (TimeoutError,urllib.error.URLError) as exc:
        raise RuntimeError("OpenAI Responses API request failed or timed out") from exc


def _output_text(response):
    if response.get("output_text"): return response["output_text"]
    for item in response.get("output",[]):
        for part in item.get("content",[]):
            if part.get("type")=="output_text": return part.get("text","")
    return ""


def _lookup(query: str, sources: dict[str,str]):
    q=query.strip().lower()
    if not q: return {"matches":[]}
    matches=[]
    for filename,content in sources.items():
        lines=content.splitlines()
        for i,line in enumerate(lines):
            if q in line.lower():
                matches.append({"file":filename,"line":i+1,"text":line[:500]})
                if len(matches)>=8: return {"matches":matches}
    return {"matches":matches}


def analyze_file(path: str, content: str, sources: dict[str,str]) -> dict:
    model=os.environ.get("GRAPHIFIER_AGENT_MODEL","gpt-6-luna")
    instructions=("Analyze source for static data lineage only. Never infer execution results. "
      "Cite exact one-based source line ranges. IDs may be arbitrary stable local IDs; relationships must reference IDs present in your entities. "
      "Use find_source_literal at most twice for a bounded literal lookup when imports/macros suggest missing context. "
      "Return only the required JSON shape. Do not repeat source content in warnings.")
    tools=[{"type":"function","name":"find_source_literal","description":"Find a case-insensitive literal in the already scanned repository and return up to eight bounded line snippets.","parameters":{"type":"object","properties":{"query":{"type":"string","maxLength":100}},"required":["query"],"additionalProperties":False}}]
    payload={"model":model,"store":False,"instructions":instructions,"input":[{"role":"user","content":f"File: {path}\nSource:\n{content}"}],"tools":tools,"text":{"format":{"type":"json_schema","name":"graphifier_extraction","strict":True,"schema":SCHEMA}},"max_output_tokens":5000}
    lookup_count=0
    for _ in range(3):
        response=_response(payload)
        calls=[x for x in response.get("output",[]) if x.get("type")=="function_call"]
        if not calls:
            text=_output_text(response)
            if not text: raise RuntimeError("Agent returned no structured extraction")
            try: result=json.loads(text)
            except json.JSONDecodeError as exc: raise RuntimeError("Agent returned invalid structured extraction") from exc
            for item in result.get("entities",[]): item["attributes"]={kv["key"]:kv["value"] for kv in item.get("attributes",[])}
            for item in result.get("relationships",[]): item["attributes"]={kv["key"]:kv["value"] for kv in item.get("attributes",[])}
            return validate(result,path,content)
        # Keep the complete response (including reasoning items) in the
        # continuation input and answer every function call, even after the
        # two-use lookup budget is exhausted.
        payload["input"].extend(response.get("output",[]))
        for call in calls:
            if call.get("name")!="find_source_literal": result={"matches":[]}
            elif lookup_count>=2: result={"matches":[],"limit_reached":True}
            else:
                lookup_count+=1
                try: result=_lookup(json.loads(call.get("arguments","{}")).get("query",""),sources)
                except (ValueError,TypeError): result={"matches":[]}
            payload["input"].append({"type":"function_call_output","call_id":call.get("call_id"),"output":json.dumps(result)})
    raise RuntimeError("Agent exceeded bounded source lookup steps")


def validate(result, path, content):
    if not isinstance(result,dict): raise RuntimeError("Agent result must be an object")
    lines=content.splitlines()
    for category in ("entities","relationships","symbols","warnings"):
        if not isinstance(result.get(category),list): raise RuntimeError(f"Agent result {category} must be a list")
    for category in ("entities","relationships","symbols"):
        for item in result[category]:
            ev=item.get("evidence",{})
            start,end=ev.get("start_line"),ev.get("end_line")
            if ev.get("file")!=path or not isinstance(start,int) or not isinstance(end,int) or start<1 or end<start or end>max(1,len(lines)):
                raise RuntimeError("Agent returned evidence outside the current source file")
    entity_ids={str(e.get("id")) for e in result["entities"]}
    for rel in result["relationships"]:
        if rel.get("source") not in entity_ids or rel.get("target") not in entity_ids:
            raise RuntimeError("Agent returned a relationship with an unknown endpoint")
    return result
