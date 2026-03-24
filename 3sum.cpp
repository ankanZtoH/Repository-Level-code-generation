#include<iostream>
#include<vector>

vector<vector<int>> threeSum(vector<int>& nums) {
        int n = nums.size();
        int target = 0;
        int temp;
        vector<vector<int>> res;
      
        int temp2;
        for(int i = 0;i<n;i++){
              map<int,int> m;
            temp = target - nums[i];
            for(int j = i+1;j<n;j++){
                temp2 = temp-nums[j];
                if(m.find(temp2) != m.end()){
                    res.push_back({nums[i],temp,nums[j]});
                }
                m[nums[j]] = j;
            }
        }

        return res;
    }
int main(){



    return 0;
}