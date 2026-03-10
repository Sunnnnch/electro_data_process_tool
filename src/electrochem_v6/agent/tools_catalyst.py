"""
Catalyst-centric tools - Query all data types for a specific sample.
以催化剂为中心的工具 - 查询特定样品的所有数据类型。
"""

from typing import Dict, Any


def tool_get_catalyst_info(sample_name: str, include_details: bool = True) -> Dict:
    """
    获取催化剂的完整信息
    
    自动查询该样品的所有可用数据:LSV, CV, EIS, ECSA
    
    Args:
        sample_name: 样品名称
        include_details: 是否包含详细数据
    
    Returns:
        包含所有数据类型的完整信息
    """
    try:
        from electrochem_v6.store.legacy_runtime import get_history_manager_v6

        hist_mgr = get_history_manager_v6()
        all_records = hist_mgr.get_all_records()
        
        # 筛选该样品的所有记录
        sample_records = [r for r in all_records if r.get('sample_name') == sample_name]
        
        if not sample_records:
            return {
                "success": False,
                "message": f"未找到样品'{sample_name}'的任何数据",
                "suggestion": "请检查样品名称是否正确,或该样品是否已处理"
            }
        
        # 按数据类型分类
        lsv_records = [r for r in sample_records if r.get('type') == 'LSV']
        cv_records = [r for r in sample_records if r.get('type') == 'CV']
        eis_records = [r for r in sample_records if r.get('type') == 'EIS']
        ecsa_records = [r for r in sample_records if r.get('type') == 'ECSA']
        
        # 构建完整信息
        catalyst_info = {
            "success": True,
            "sample_name": sample_name,
            "total_records": len(sample_records),
            "data_types_available": []
        }
        
        # LSV数据
        if lsv_records:
            catalyst_info["data_types_available"].append("LSV")
            lsv_results = [r.get('results', {}) for r in lsv_records]
            
            # 计算平均值(如果有多次测量)
            eta_values = [res.get('overpotential_10') for res in lsv_results if res.get('overpotential_10')]
            tafel_values = [res.get('tafel_slope') for res in lsv_results if res.get('tafel_slope')]
            
            catalyst_info["lsv"] = {
                "record_count": len(lsv_records),
                "overpotential_10": sum(eta_values) / len(eta_values) if eta_values else None,
                "tafel_slope": sum(tafel_values) / len(tafel_values) if tafel_values else None,
                "latest_time": lsv_records[-1].get('timestamp'),
                "performance_level": _evaluate_lsv_performance(
                    sum(eta_values) / len(eta_values) if eta_values else None,
                    sum(tafel_values) / len(tafel_values) if tafel_values else None
                )
            }
            
            if include_details:
                catalyst_info["lsv"]["all_measurements"] = [
                    {
                        "time": r.get('timestamp'),
                        "eta_10": r.get('results', {}).get('overpotential_10'),
                        "tafel": r.get('results', {}).get('tafel_slope')
                    } for r in lsv_records
                ]
        
        # CV数据
        if cv_records:
            catalyst_info["data_types_available"].append("CV")
            cv_results = cv_records[-1].get('results', {})  # 使用最新记录
            
            catalyst_info["cv"] = {
                "record_count": len(cv_records),
                "potential_range": cv_results.get('potential_range'),
                "current_range": cv_results.get('current_range'),
                "data_points": cv_results.get('data_points'),
                "latest_time": cv_records[-1].get('timestamp')
            }
        
        # EIS数据
        if eis_records:
            catalyst_info["data_types_available"].append("EIS")
            eis_results = [r.get('results', {}) for r in eis_records]
            
            # 平均Rs和Rct
            rs_values = [res.get('Rs') for res in eis_results if res.get('Rs')]
            rct_values = [res.get('Rct') for res in eis_results if res.get('Rct')]
            
            catalyst_info["eis"] = {
                "record_count": len(eis_records),
                "Rs": sum(rs_values) / len(rs_values) if rs_values else None,
                "Rct": sum(rct_values) / len(rct_values) if rct_values else None,
                "latest_time": eis_records[-1].get('timestamp')
            }
        
        # ECSA数据
        if ecsa_records:
            catalyst_info["data_types_available"].append("ECSA")
            ecsa_results = [r.get('results', {}) for r in ecsa_records]
            
            # 平均Cdl和ECSA
            cdl_values = [res.get('Cdl') for res in ecsa_results if res.get('Cdl')]
            ecsa_values = [res.get('ECSA') for res in ecsa_results if res.get('ECSA')]
            rf_values = [res.get('RF') for res in ecsa_results if res.get('RF')]
            
            catalyst_info["ecsa"] = {
                "record_count": len(ecsa_records),
                "Cdl": sum(cdl_values) / len(cdl_values) if cdl_values else None,
                "ECSA": sum(ecsa_values) / len(ecsa_values) if ecsa_values else None,
                "RF": sum(rf_values) / len(rf_values) if rf_values else None,
                "latest_time": ecsa_records[-1].get('timestamp')
            }
        
        # 生成综合评价
        catalyst_info["overall_assessment"] = _generate_overall_assessment(catalyst_info)
        
        return catalyst_info
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def _evaluate_lsv_performance(eta: float = None, tafel: float = None) -> str:
    """评估LSV性能等级"""
    if eta is None:
        return "未知"
    
    if eta < 0.10:
        return "⭐⭐⭐⭐⭐ 卓越(商业Pt/C级别)"
    elif eta < 0.30:
        return "⭐⭐⭐⭐ 优秀"
    elif eta < 0.40:
        return "⭐⭐⭐ 良好"
    elif eta < 0.50:
        return "⭐⭐ 一般"
    else:
        return "⭐ 需要改进"


def _generate_overall_assessment(info: Dict) -> str:
    """生成综合评价"""
    available_types = info.get('data_types_available', [])
    
    if not available_types:
        return "无可用数据"
    
    assessments = []
    
    # LSV评价
    if 'LSV' in available_types and info.get('lsv'):
        lsv = info['lsv']
        assessments.append(f"LSV性能:{lsv.get('performance_level', '未评估')}")
    
    # EIS评价
    if 'EIS' in available_types and info.get('eis'):
        eis = info['eis']
        if eis.get('Rs'):
            if eis['Rs'] < 10:
                assessments.append("EIS:溶液阻抗低(良好)")
            else:
                assessments.append("EIS:溶液阻抗较高")
    
    # ECSA评价
    if 'ECSA' in available_types and info.get('ecsa'):
        ecsa = info['ecsa']
        if ecsa.get('ECSA'):
            if ecsa['ECSA'] > 1.0:
                assessments.append("ECSA:活性面积大(优秀)")
            else:
                assessments.append("ECSA:活性面积一般")
    
    if assessments:
        return "; ".join(assessments)
    else:
        return f"有{len(available_types)}种类型的数据"


__all__ = ["tool_get_catalyst_info"]

