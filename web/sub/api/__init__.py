
from fastapi import APIRouter
from .sub_api import router as sub_router
from .robo_payment.payment_api import router as robo_payment_router
from ..config_dir.config import ArqDep

main_router = APIRouter()

main_router.include_router(sub_router)
main_router.include_router(robo_payment_router)

@main_router.get('/healthcheck')
async def health_checking(arq: ArqDep):
    arq_jobs = await arq.queued_jobs()
    # log_event(f'arq_jobs {arq_jobs}, len_arq_jobs {len(arq_jobs)}', level='DEBUG')
    return {'status': True, 'arq_jobs': len(arq_jobs), 'version': '1.0', 'service': 'sub-service'}