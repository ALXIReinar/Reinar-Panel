import { Sessions } from '$lib/api/auth/calls';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
    let sessions = await Sessions();

    // if (sessions.length === 0) {
    //     redirect(307, AppRoutes.Login());
    // } else {
    //     redirect(307, AppRoutes.DashboardIndex());
    // }
};
